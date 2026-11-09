from __future__ import annotations

import inspect
import json
import uuid
from pathlib import Path
from typing import Any

from .core import HomeAssistant
from .entity import EntityPlatform
from .errors import DuplicateEntry, IntegrationSetupError
from .flow import AbortFlow, ConfigFlow
from .loader import inspect_package, load_package
from .mapping import project_entity
from .models import ConfigEntry, EntryState
from .network import ControlledSession, NetworkPolicy
from .registry import RegistryStore
from .security import CredentialVault, split_secrets



def _pick_config_flow(module, domain: str):
    """从集成模块里挑出 ConfigFlow 子类。

    # ## 不能写死 getattr(module, "ConfigFlow")（2026-11-01 实测）

    HA 的约定是「集成自己命名一个 ConfigFlow 子类」，名字通常带集成前缀
    （midea_ac_lan 是 `MideaLanConfigFlow`）。真实 HA 靠 config_entries 的
    注册表按 domain 找到它；我们的兼容层没有那套注册表，所以按下面顺序找：
      ① 名字里含集成前缀的 ConfigFlow 子类（最常见）
      ② 任何 ConfigFlow 子类
      ③ 兜底才是模块里那个名叫 ConfigFlow 的（可能是 import 进来的基类）
    """
    from homeassistant.config_entries import ConfigFlow as BaseFlow

    candidates = []
    for name, obj in vars(module).items():
        if not isinstance(obj, type) or obj is BaseFlow:
            continue
        try:
            if not issubclass(obj, BaseFlow):
                continue
        except TypeError:
            continue
        # 排除从其它模块 import 进来的
        if getattr(obj, "__module__", "") != module.__name__:
            continue
        candidates.append((name, obj))

    # ① 名字里沾 domain 的片段
    domain_parts = [p for p in domain.split("_") if p]
    for name, obj in candidates:
        low = name.lower()
        if all(p in low for p in domain_parts):
            return obj
    # ② 第一个子类
    if candidates:
        return candidates[0][0] and candidates[0][1]
    # ③ 兜底
    return getattr(module, "ConfigFlow")


class IntegrationRuntime:
    """One household/source namespace. Never connects to an HA server."""

    def __init__(self, root: Path, namespace: str, master_key: bytes, sink=None,
                 network_policy: NetworkPolicy | None = None) -> None:
        self.root, self.namespace, self.sink = root, namespace, sink
        root.mkdir(parents=True, exist_ok=True)
        self.registry = RegistryStore(root / "registry.json", namespace)
        self.vault = CredentialVault(root / "secrets", master_key)
        self.network_session = ControlledSession(network_policy or NetworkPolicy())
        self.entries: dict[str, ConfigEntry] = {}
        # ## 未完成的 config flow 必须**跨调用保留**（2026-11-09 修 midea 报错）
        #
        # HA 的 config_flow 是**有状态**的：实例在 async_step_user 里把发现到的
        # 设备列表存进 self.devices，下一步 async_step_auto 再从那里按 id 取。
        # 而平台此前每次 invoke 都 `flow_cls()` 新建一个实例 —— 第二步拿到的
        # 是空实例，`self.devices[device_id]` 直接 KeyError，用户看到的是
        # 「HXCS_ERROR: 208907212949996」（一个没有说明的设备 ID，实测）。
        #
        # HA 原生用 hass.config_entries.flow 缓存活动流程；这里等价地按
        # (domain, handle) 保留实例。handle 由下一处注释说明。
        self._flows: dict[tuple[str, str], Any] = {}
        self.integrations: dict[str, tuple[Any, Any]] = {}
        self.platforms: dict[tuple[str, str], EntityPlatform] = {}
        self._load_entries()
        self.hass: HomeAssistant | None = None

    async def start(self):
        async def projector(state):
            if state is not None and self.sink:
                result = self.sink(project_entity(self.namespace, state.entity_id.split(".", 1)[0], state))
                if inspect.isawaitable(result): await result
        self.hass = HomeAssistant(projector=projector)
        self.hass.config_entries = self
        self.hass.data["hx_registry"] = self.registry
        self.hass.data["hx_http_session"] = self.network_session
        return self

    def install(self, path: Path):
        package = inspect_package(path)
        module = load_package(package)
        self.integrations[package.domain] = (package, module)
        return package

    async def run_config_flow(self, domain: str, user_input: dict[str, Any] | None = None,
                             step: str = "user", flow_handle: str | None = None):
        package, _ = self.integrations[domain]
        flow_module = __import__(f"{package.module_name}.config_flow", fromlist=["ConfigFlow"])
        flow_cls = _pick_config_flow(flow_module, domain)
        # ## 流程实例复用（2026-11-09）
        #
        # handle 由调用方给（worker 侧从 payload 取，前端每轮流程带同一个）。
        # 缺失时退化成一次性实例（保持旧行为，不因缺 handle 而失败）。
        handle = str(flow_handle or "")
        key = (domain, handle) if handle else None
        flow: ConfigFlow | None = self._flows.get(key) if key else None
        if flow is None:
            flow = flow_cls()
            flow.hass = self.hass
            if key:
                self._flows[key] = flow
        else:
            flow.hass = self.hass
        try:
            result = await getattr(flow, f"async_step_{step}")(user_input)
        except AbortFlow as exc:
            # 集成主动终止（already_configured / single_instance_allowed 等）
            return {"type": "abort", "reason": exc.reason}
        # 流程终结时丢掉实例：create_entry 之后再复用会把"已完成"的流程
        # 当成进行中的（用户下次添加同型号设备会撞 already_configured）。
        if key and result.get("type") in ("create_entry", "abort"):
            self._flows.pop(key, None)
        if result.get("type") == "create_entry":
            unique = result.get("unique_id")
            if unique and any(e.domain == domain and e.unique_id == unique for e in self.entries.values()):
                raise DuplicateEntry(f"duplicate unique_id for {domain}: {unique}")
            entry_id = uuid.uuid4().hex
            public, secrets = split_secrets(result["data"])
            if secrets: self.vault.put(self.namespace, entry_id, secrets)
            entry = ConfigEntry(domain, result["title"], public, result.get("options", {}), entry_id, unique)
            self.entries[entry_id] = entry
            self._save_entries()
            result = {**result, "entry_id": entry_id, "data": public}
        return result

    def entry_data(self, entry: ConfigEntry) -> dict[str, Any]:
        return {**entry.data, **self.vault.get(self.namespace, entry.entry_id)}

    async def async_setup(self, entry_id: str) -> bool:
        entry = self.entries[entry_id]
        _, module = self.integrations[entry.domain]
        try:
            entry._runtime_data = self.entry_data(entry)
            ok = await module.async_setup_entry(self.hass, entry) if hasattr(module, "async_setup_entry") else True
            entry.state = EntryState.LOADED if ok else EntryState.SETUP_ERROR
            self._save_entries()
            return bool(ok)
        except Exception as exc:
            entry.state = EntryState.SETUP_ERROR
            self._save_entries()
            if isinstance(exc, IntegrationSetupError):
                raise
            raise IntegrationSetupError(
                f"integration {entry.domain} failed during setup: {type(exc).__name__}: {exc}",
                domain=entry.domain, phase="setup_entry",
            ) from exc
        finally:
            entry._runtime_data = None

    async def async_unload(self, entry_id: str) -> bool:
        entry = self.entries[entry_id]
        _, module = self.integrations[entry.domain]
        ok = await module.async_unload_entry(self.hass, entry) if hasattr(module, "async_unload_entry") else True
        if ok:
            for (eid, _), platform in list(self.platforms.items()):
                if eid == entry_id:
                    await platform.async_remove(); self.platforms.pop((eid, platform.domain), None)
            entry.state = EntryState.NOT_LOADED
            self._save_entries()
        return bool(ok)

    async def async_forward_entry_setups(self, entry: ConfigEntry, platforms):
        package, _ = self.integrations[entry.domain]
        for domain in platforms:
            try:
                module = __import__(f"{package.module_name}.{domain}", fromlist=["async_setup_entry"])
                platform = EntityPlatform(self.hass, self.registry, entry, domain)
                self.platforms[(entry.entry_id, domain)] = platform
                await module.async_setup_entry(self.hass, entry, platform.async_add_entities)
            except Exception as exc:
                failed = self.platforms.pop((entry.entry_id, domain), None)
                if failed:
                    await failed.async_remove()
                raise IntegrationSetupError(
                    f"integration {entry.domain} platform {domain} failed: {type(exc).__name__}: {exc}",
                    domain=entry.domain, phase=f"platform:{domain}",
                ) from exc
        return True

    async def async_unload_platforms(self, entry: ConfigEntry, platforms):
        for domain in platforms:
            platform = self.platforms.pop((entry.entry_id, domain), None)
            if platform: await platform.async_remove()
        return True

    async def async_reload(self, entry_id: str):
        await self.async_unload(entry_id)
        return await self.async_setup(entry_id)

    async def async_remove(self, entry_id: str) -> bool:
        """Fully remove an entry and every resource owned by it."""
        entry = self.entries[entry_id]
        if entry.state == EntryState.LOADED and not await self.async_unload(entry_id):
            return False
        removed_entity_ids = self.registry.remove_config_entry(entry_id)
        for entity_id in removed_entity_ids:
            await self.hass.states.async_remove(entity_id)
        owned = self.hass.data.pop(f"hx_services:{entry_id}", [])
        for domain, service in owned:
            self.hass.services.async_remove(domain, service)
        self.vault.delete(self.namespace, entry_id)
        self.entries.pop(entry_id, None)
        self._save_entries()
        return True

    def register_entry_service(self, entry_id: str, domain: str, service: str, handler, schema=None):
        self.hass.services.async_register(domain, service, handler, schema)
        self.hass.data.setdefault(f"hx_services:{entry_id}", []).append((domain, service))

    def _save_entries(self):
        data = [{"domain": e.domain, "title": e.title, "data": e.data, "options": e.options,
                 "entry_id": e.entry_id, "unique_id": e.unique_id, "state": e.state.value}
                for e in self.entries.values()]
        (self.root / "entries.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_entries(self):
        path = self.root / "entries.json"
        if not path.exists(): return
        for raw in json.loads(path.read_text(encoding="utf-8")):
            raw["state"] = EntryState(raw["state"])
            entry = ConfigEntry(**raw)
            self.entries[entry.entry_id] = entry
