from __future__ import annotations

import inspect
import json
import uuid
from pathlib import Path
from typing import Any

from .core import HomeAssistant
from .entity import EntityPlatform
from .errors import DuplicateEntry, IntegrationSetupError
from .flow import ConfigFlow
from .loader import inspect_package, load_package
from .mapping import project_entity
from .models import ConfigEntry, EntryState
from .network import ControlledSession, NetworkPolicy
from .registry import RegistryStore
from .security import CredentialVault, split_secrets


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

    async def run_config_flow(self, domain: str, user_input: dict[str, Any] | None = None, step: str = "user"):
        package, _ = self.integrations[domain]
        flow_module = __import__(f"{package.module_name}.config_flow", fromlist=["ConfigFlow"])
        flow_cls = getattr(flow_module, "ConfigFlow")
        flow: ConfigFlow = flow_cls()
        flow.hass = self.hass
        result = await getattr(flow, f"async_step_{step}")(user_input)
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
