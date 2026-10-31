#!/usr/bin/env python3
"""HXCS 合并版 Worker：社区商店 + HA 兼容运行时。

替代原 HXCS（WASM/Go）+ HX-Ha_Bridge（Python）两个插件，
合并为一个 Python 运行时插件。

工具清单：
  catalog_list       → 拉取社区注册表（GitHub）
  catalog_fetch      → 下载指定插件的 .hpkg 字节
  community_status   → 查询社区开关状态
  integration_load   → 加载 HA 风格集成包（映射到 op=load）
  config_flow        → 执行配置流程步骤
  entry_setup        → 启动 config entry
  entry_reload       → 重载 entry
  entry_remove       → 删除 entry
  service_call       → 调用集成内注册的服务

stdin/stdout JSON lines 是宿主控制面，与 HX-Ha_Bridge 同一协议。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from hx_ha_runtime.runtime import IntegrationRuntime


class HxcsWorker:
    def __init__(self) -> None:
        self.runtime: IntegrationRuntime | None = None
        self.generation = 0
        self.draining = False
        self.config: dict[str, Any] = {}
        self.catalog_cache: dict[str, Any] | None = None

    # —— 配置 ——————————————————————————————————————————————

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    @property
    def community_enabled(self) -> bool:
        return bool(self._cfg("community_enabled", False))

    @property
    def ha_compat_enabled(self) -> bool:
        return bool(self._cfg("ha_compat_enabled", False))

    @property
    def registry_url(self) -> str:
        return str(self._cfg("registry_url", "https://raw.githubusercontent.com/1169892406/HXCS/main"))

    # —— HTTP 工具（Python 直连，不走宿主 session）—————————————————

    def _http_get(self, url: str, max_bytes: int = 32 * 1024 * 1024) -> bytes:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        # 代理支持
        proxy = str(self._cfg("proxy_url", ""))
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({
                "http": proxy, "https": proxy,
            }))
        opener = urllib.request.build_opener(*handlers) if handlers else urllib.request
        with opener.open(req, timeout=15) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {url}")
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError(f"响应超过 {max_bytes} 字节")
            return data

    # —— 社区商店工具 ————————————————————————————————————————

    def op_catalog_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        """拉取注册表 index.json，返回插件清单。"""
        if not self.community_enabled:
            raise RuntimeError("社区插件未启用：请在 HXCS 配置页打开「启用社区插件」")
        url = self.registry_url.rstrip("/") + "/index.json"
        body = self._http_get(url, max_bytes=1 << 20)
        idx = json.loads(body)
        # ha_compat 关闭时过滤 HA 集成包
        if not self.ha_compat_enabled:
            idx["plugins"] = [p for p in idx.get("plugins", []) if p.get("type") != "ha_integration"]
        return idx

    def op_catalog_fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """下载指定插件的 .hpkg 字节（base64 + sha256）。"""
        if not self.community_enabled:
            raise RuntimeError("社区插件未启用")
        package_url = str(payload.get("package_url", ""))
        if not package_url or "://" in package_url or package_url.startswith("/"):
            raise RuntimeError("package_url 必须是注册表内相对路径")
        url = self.registry_url.rstrip("/") + "/" + package_url
        body = self._http_get(url, max_bytes=32 << 20)
        got = hashlib.sha256(body).hexdigest()
        expected = str(payload.get("expect_sha256", "")).lower()
        if expected and got != expected:
            raise RuntimeError(f"包摘要不匹配：期望 {expected[:16]}… 实际 {got[:16]}…")
        return {
            "package_b64": base64.b64encode(body).decode("ascii"),
            "sha256": got,
            "size": len(body),
        }

    def op_community_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """查询社区开关状态。"""
        return {
            "enabled": self.community_enabled,
            "registry": self.registry_url,
            "registry_v": "1",
            "ha_compat": self.ha_compat_enabled,
            "proxy_url": str(self._cfg("proxy_url", "")),
        }

    # —— HA 集成管理 ——————————————————————————————————————

    def op_integrations_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        """列出可加载的集成（root/integrations/ 下）+ 已加载的集成。"""
        result = {"available": [], "loaded": [], "ha_compat": self.ha_compat_enabled}
        # 扫描 root/integrations/ 目录（prepare 时记录的 runtime_root）
        rroot = getattr(self, "runtime_root", "")
        if rroot:
            integ_dir = Path(rroot) / "integrations"
            if integ_dir.is_dir():
                for d in sorted(integ_dir.iterdir()):
                    if d.is_dir() and (d / "manifest.json").exists():
                        mf = json.loads((d / "manifest.json").read_text())
                        result["available"].append({
                            "domain": mf.get("domain", d.name),
                            "name": mf.get("name", d.name),
                            "version": mf.get("version", ""),
                            "config_flow": mf.get("config_flow", False),
                            "path": str(d),
                        })
        # 已加载的
        if self.runtime:
            for entry_id, entry in getattr(self.runtime, "entries", {}).items():
                result["loaded"].append({
                    "domain": entry.domain,
                    "entry_id": entry_id,
                    "state": entry.state.value if hasattr(entry.state, "value") else str(entry.state),
                })
        return result

    # —— HA 运行时工具（从 HX-Ha_Bridge 移植）———————————————

    def op_load(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.ha_compat_enabled:
            raise RuntimeError("HA 兼容未启用：请在 HXCS 配置页打开「兼容 HA 插件」")
        self._accept_mutation()
        package = self.runtime.install(Path(payload["path"]))
        return {"domain": package.domain, "manifest": package.manifest}

    async def op_config_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_ha()
        self._accept_mutation()
        return await self.runtime.run_config_flow(
            payload["domain"], payload.get("input"), payload.get("step", "user")
        )

    async def op_entry_setup(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_ha()
        self._accept_mutation()
        return {"ok": await self.runtime.async_setup(payload["entry_id"])}

    async def op_entry_reload(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_ha()
        self._accept_mutation()
        return {"ok": await self.runtime.async_reload(payload["entry_id"])}

    async def op_entry_remove(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_ha()
        self._accept_mutation()
        return {"ok": await self.runtime.async_remove(payload["entry_id"])}

    async def op_service_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_ha()
        self._accept_mutation()
        value = await self.runtime.hass.services.async_call(
            payload["domain"], payload["service"], payload.get("data"), blocking=True
        )
        return {"result": value}

    # —— 生命周期 ——————————————————————————————————————————

    def op_health(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"state": "draining" if self.draining else "ready",
                "ha_runtime": self.runtime is not None,
                "community": self.community_enabled,
                "ha_compat": self.ha_compat_enabled}

    async def op_drain(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.draining = True
        if self.runtime:
            await self.runtime.hass.async_block_till_done()
        return {"state": "drained"}

    async def op_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.draining = True
        if self.runtime:
            for entry_id in tuple(self.runtime.entries):
                if self.runtime.entries[entry_id].state.value == "loaded":
                    await self.runtime.async_unload(entry_id)
            await self.runtime.hass.async_block_till_done()
        return {"state": "stopped", "exit": True}

    # —— 内部 ——————————————————————————————————————————————

    def _require_ha(self) -> None:
        if self.runtime is None:
            raise RuntimeError("HA 运行时未初始化")
        if int(getattr(self, '_cur_gen', 0)) != self.generation:
            raise RuntimeError("HA_COMPAT_STALE_GENERATION")

    def _accept_mutation(self) -> None:
        if self.draining:
            raise RuntimeError("HA_COMPAT_DRAINING")

    # —— 分发 ——————————————————————————————————————————————

    async def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "prepare":
            self.generation = int(request["generation"])
            root = Path(request["root"])
            self.runtime_root = str(root)
            namespace = str(request["namespace"])
            # 读取配置（平台通过 prepare 传入）
            self.config = request.get("config", {})
            key_hex = os.environ.pop("HX_HA_MASTER_KEY", "")
            # 初始化 HA 运行时（如果需要）
            if len(key_hex) == 64:
                self.runtime = await IntegrationRuntime(root, namespace, bytes.fromhex(key_hex)).start()
            return {"generation": self.generation, "state": "prepared",
                    "ha_runtime": self.runtime is not None,
                    "community": self.community_enabled}

        # 生成校验
        self._cur_gen = int(request.get("generation", 0))
        if self._cur_gen != self.generation:
            raise RuntimeError("HA_COMPAT_STALE_GENERATION")

        # 分发
        handler = getattr(self, f"op_{op}", None)
        if handler is None:
            raise RuntimeError(f"unsupported operation: {op}")

        result = handler(request)
        # 如果 result 是 coroutine（async 方法），await 它
        if asyncio.iscoroutine(result):
            result = await result
        return result


async def main() -> None:
    worker = HxcsWorker()
    loop = asyncio.get_event_loop()
    while line := await asyncio.to_thread(sys.stdin.readline):
        try:
            request = json.loads(line)
            result = await worker.dispatch(request)
            response = {"id": request.get("id"), "ok": True, "result": result}
        except Exception as exc:
            response = {"id": request.get("id") if "request" in locals() else None,
                        "ok": False,
                        "error": {"code": getattr(exc, "code", "HXCS_ERROR"),
                                   "message": str(exc)}}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
