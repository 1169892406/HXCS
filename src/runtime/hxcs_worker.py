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

# ## vendored 依赖放成 zip 而不是目录（2026-11-01 实测约束）
#
# 插件的 .hpkg 有**包内文件数上限**（256）。把 aiohttp/pycryptodome/
# midealan 展开成目录是 588 个文件，直接超限打包失败。
# 打成单个 vendor.zip 后包内只算 1 个文件；Python 的 zipimport
# 原生支持从 zip 里 import 纯 Python 与 .so（3.12 起 .so 也支持）。
import os, sys


def _bootstrap_vendor() -> None:
    """把 vendored 依赖解压到持久化目录并加进 sys.path。

    # ## 为什么必须解压而不是直接从 zip import（2026-11-01 实测）

    优化前的做法是把依赖打成一个 vendor.zip（为了绕过 .hpkg 的
    256 文件上限）。但 **zipimport 不支持原生扩展**：
    pycryptodome 的 Crypto.Util._cpuid_c.cpython-312-x86_64-linux-gnu.so
    从 zip 里加载直接报 "Cannot load native module"。
    midealan 用 AES 加密设备通信，没有它集成完全不可用。

    所以：zip 打在包里（只占 1 个文件名额），首次启动**解压**到
    持久化目录（data/plugins/fs/<家庭>/hxcs.vendor/），之后所有代际
    直接复用（跨版本保留，不会每次升级都解压一遍）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(here, "vendor.zip")
    if not os.path.isfile(zip_path):
        return
    # ## 解压目标必须跨版本保留
    #
    # here = <data>/plugins/versions/<plugin_id>/<version>/runtime
    # → here.parents[3] = <data>/plugins，持久化区放 <data>/plugins/
    # 这样热升级重建物化目录后仍能复用已解压的依赖（不用每次重解压 6.5MB）。
    try:
        from pathlib import Path
        plugins_root = Path(here).parents[3]
        target = str(plugins_root / "hxcs-vendor")
    except (IndexError, OSError):
        target = os.path.join(here, "vendor-unpacked")
    marker = os.path.join(target, ".ok")
    if not os.path.isfile(marker):
        import zipfile, tempfile, shutil
        # ## 临时目录必须与目标同一文件系统（2026-11-01 实测）
        #
        # 原来用 tempfile.mkdtemp() 落在 /tmp（tmpfs），
        # os.replace 到 /opt（磁盘）直接报 Invalid cross-device link。
        # 改成在**目标父目录**建临时目录，最后 rename 过去（同设备，原子）。
        parent = os.path.dirname(target) or "."
        os.makedirs(parent, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".hxcs-vendor-tmp-", dir=parent)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            os.replace(tmp, target)
            tmp = None
            with open(marker, "w") as fh:
                fh.write("ok")
        finally:
            if tmp and os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
    if target not in sys.path:
        sys.path.insert(0, target)


_bootstrap_vendor()

import asyncio
import base64
import hashlib
import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

from hx_ha_runtime.runtime import IntegrationRuntime


# —— config_flow 结果序列化 ——————————————————————————————————————

def _selector_of(marker) -> dict[str, Any]:
    """从 voluptuous 的标记对象里捞出字段元信息。

    voluptuous 把每个字段包成 vol.Required(...)/vol.Optional(...)，
    value 位置可能是：
      · 裸字符串 → 普通文本框
      · vol.In({...}) / vol.In([...]) → 下拉选项 + 默认值
      · 某个 Selector 实例（HA selector）→ 按 selector 类型判断控件
    这个函数只做"翻译"，不做校验 —— 校验仍由 voluptuous 在提交时做。
    """
    info: dict[str, Any] = {}
    # ## voluptuous 各标记对象的真实字段名（实测）
    #
    #   vol.In({...})  → .container  （不是 .schema！）
    #   vol.Required   → .default / .schema 包着内层
    #   Selector       → .config
    # 先把 Required/Optional 这层剥掉，再按内层对象的类型取候选值。
    inner = marker
    if hasattr(inner, "schema") and not isinstance(inner, (dict, list, str)):
        # vol.Required(x, default=y)：schema 是 x，default 在外层
        if getattr(inner, "default", None) is not None and not callable(inner.default):
            info["default"] = inner.default
        inner = inner.schema
    elif getattr(marker, "default", None) is not None and not callable(marker.default):
        info["default"] = marker.default

    container = getattr(inner, "container", None)
    val = container if container is not None else getattr(inner, "schema", inner)
    if isinstance(val, dict):
        info["options"] = [{"value": str(k), "label": str(v) if v != k else str(k)}
                           for k, v in val.items()]
        info["type"] = "select"
    elif isinstance(val, (list, tuple, set)):
        info["options"] = [{"value": str(x), "label": str(x)} for x in val]
        info["type"] = "select"
    elif hasattr(val, "as_selector"):
        # HA 的 selector
        cfg = getattr(val, "config", None)
        if cfg is not None and hasattr(cfg, "type"):
            info["type"] = "password" if cfg.type == "password" else "text"
        elif hasattr(cfg, "options"):
            info["options"] = [
                {"value": str(o.value if hasattr(o, "value") else o),
                 "label": str(o.label if hasattr(o, "label") else o)}
                for o in cfg.options
            ]
            info["type"] = "select"
        else:
            info["type"] = "text"
    return info


def _flow_result_to_json(result: dict[str, Any]) -> dict[str, Any]:
    """把 run_config_flow 的返回值拍平成前端可读的 JSON。"""
    out: dict[str, Any] = {"type": result.get("type", "unknown")}
    if result.get("step_id"):
        out["step_id"] = result["step_id"]
    if result.get("errors"):
        out["errors"] = result["errors"]
    if result.get("reason"):
        out["reason"] = result["reason"]
    if result.get("title"):
        out["title"] = result["title"]
    if result.get("entry_id"):
        out["entry_id"] = result["entry_id"]
    if result.get("description_placeholders"):
        out["description_placeholders"] = result["description_placeholders"]
    if result.get("data") is not None:
        out["data"] = result["data"]

    schema = result.get("data_schema")
    if schema is not None:
        fields = []
        raw = getattr(schema, "schema", schema)
        if isinstance(raw, dict):
            for key, marker in raw.items():
                # ## voluptuous 的 key 也可能是标记对象（2026-11-01 实测）
                #
                # 写法是 `{vol.Required("action", default="discovery"): vol.In({...})}`
                # —— Required 包在 **key** 上，不在 value 上。所以：
                #   · 真实字段名 = key.schema（不是 str(key)，那会印成 "Required(...)"）
                #   · required / default 都在 key 上
                #   · 候选值在 value（vol.In）的 .container 上
                real_key = key
                required = False
                default = None
                if hasattr(key, "schema") and not isinstance(key, (str, dict, list)):
                    # str(key) 会调用 voluptuous 的 __str__，正确输出字段名
                    real_key = str(key)
                    required = bool(getattr(key, "required", False))
                    d = getattr(key, "default", None)
                    if d is not None:
                        # default 可能是值，也可能是 defau< lamb达（vol 的
                        # default_factory 会包一层 lambda）；两种都取到真值
                        if callable(d):
                            try:
                                d = d()
                            except Exception:
                                d = None
                        if d is not None and not callable(d):
                            default = d
                field = {"key": str(real_key), **_selector_of(marker)}
                if default is not None:
                    field["default"] = default
                field["required"] = required
                fields.append(field)
        out["fields"] = fields
    return out


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
        opener = urllib.request.build_opener(*handlers)  # 空 handlers = 默认直连
        # ## 强制 IPv4（2026-11-01 新机器迁移实测踩坑）
        #
        # raw.githubusercontent.com DNS 返回 IPv6 优先；新机器 IPv6 不通，
        # python 走 IPv6 → TLS 握手超时 40s → 平台判定 worker 卡死 → broken pipe。
        # curl 能通是因为它 Happy Eyeballs 回落 IPv4。这里显式过滤掉 IPv6，
        # 让 urllib 只连 IPv4（185.199.108.x），根治握手超时。
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https" and parsed.hostname:
            import socket as _socket
            orig = _socket.getaddrinfo
            def v4_only(host, port, family=0, *a, **kw):
                return [x for x in orig(host, port, family, *a, **kw)
                        if x[0] == _socket.AF_INET]
            _socket.getaddrinfo = v4_only
            try:
                with opener.open(req, timeout=45) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}: {url}")
                    data = resp.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise RuntimeError(f"响应超过 {max_bytes} 字节")
                    return data
            finally:
                _socket.getaddrinfo = orig
        with opener.open(req, timeout=45) as resp:
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
        """列出可加载的集成 + 已加载的集成。

        # ## 扫描持久化目录而不是物化目录（2026-11-01 修复）

        物化目录（prepare 的 root）每次热升级都会从包重建，手动放进
        <version>/integrations/ 的集成在下一次升级就"消失"。改为扫描
        持久化层 data/plugins/fs/<namespace>/<plugin_id>/integrations/——
        这个目录跨版本保留。物化目录里的 integrations 也扫（兼容旧数据）。
        """
        result = {"available": [], "loaded": [], "ha_compat": self.ha_compat_enabled}
        seen = set()
        # 候选目录：持久化目录 + 物化目录（后者兼容手工放置）
        #
        # ## 路径推导修正（2026-11-01 平台实测）
        #
        # prepare 的 root 字段传的是 stateRoot（runtime/<pid>/<hh>），不是
        # 物化目录；之前用 parents[2] 推导全错，导致平台调用时 available
        # 恒为空。真正的物化目录是进程 cwd（resolver 的 g.Path），
        # 形如 <data>/plugins/versions/<pid>/<ver> → cwd.parents[2] = plugins。
        candidates = []
        ns = getattr(self, "namespace", "")
        cwd = Path.cwd()
        try:
            data_plugins = cwd.parents[2]
        except IndexError:
            data_plugins = None
        if ns and data_plugins and (data_plugins / "fs").is_dir():
            candidates.append(data_plugins / "fs" / ns / "homex.hxcs" / "integrations")
        # 物化目录本身（手工放置兼容）+ stateRoot（历史版本曾放这里）
        rroot = getattr(self, "runtime_root", "")
        if rroot:
            candidates.append(Path(rroot) / "integrations")
        for integ_dir in candidates:
            if not integ_dir.is_dir():
                continue
            for d in sorted(integ_dir.iterdir()):
                if not (d.is_dir() and (d / "manifest.json").exists()):
                    continue
                mf = json.loads((d / "manifest.json").read_text())
                domain = mf.get("domain", d.name)
                if domain in seen:
                    continue
                seen.add(domain)
                result["available"].append({
                    "domain": domain,
                    "name": mf.get("name", d.name),
                    "version": mf.get("version", ""),
                    "description": mf.get("description", ""),
                    "config_flow": mf.get("config_flow", False),
                    "path": str(d),
                })
        # ## 补 GitHub 星数（用户 2026-11-02）
        #
        # 本地集成目录里没有星数——它只存在于注册表 index.json 的条目上。
        # 卡片要显示"这个集成的 GitHub 仓库有多少星"，所以这里顺手读一次
        # 注册表把 github_stars 合进来。读失败就当 0（不阻塞列表）。
        try:
            reg_url = self.registry_url.rstrip("/") + "/index.json"
            raw = self._http_get(reg_url, max_bytes=1 << 20)
            reg = json.loads(raw)
            stars = {p.get("plugin_id"): p.get("github_stars", 0)
                     for p in reg.get("plugins", [])}
            for item in result["available"]:
                if item["domain"] in stars:
                    item["github_stars"] = stars[item["domain"]]
        except Exception:
            for item in result["available"]:
                item.setdefault("github_stars", 0)

        # 已加载的：优先看 entries（已 setup 的 config entry）；
        # 没有 entry 的看 runtime.installed（install 后已注册但还没配设备的）
        if self.runtime:
            for entry_id, entry in getattr(self.runtime, "entries", {}).items():
                result["loaded"].append({
                    "domain": entry.domain,
                    "entry_id": entry_id,
                    "state": entry.state.value if hasattr(entry.state, "value") else str(entry.state),
                })
            # runtime.integrations 是 install() 后已注册的包字典
            for domain in getattr(self.runtime, "integrations", {}).keys():
                if not any(l["domain"] == domain for l in result["loaded"]):
                    result["loaded"].append({"domain": domain, "entry_id": "", "state": "installed"})
        return result

    def op_integration_install(self, payload: dict[str, Any]) -> dict[str, Any]:
        """下载 HA 集成 zip 并解压到持久化 integrations 目录。

        # ## 为什么不走浏览器 + installFromPackage（2026-11-01 实测）

        两个硬障碍：
          ① HA 集成是 zip，而 installFromPackage 只接 .hpkg；
          ② 浏览器 crypto.subtle 只在 HTTPS/localhost 可用，
             http 访问时 undefined（用户报 "Cannot read properties of undefined (reading 'digest')"）。

        改由 worker 自己下载（走 proxy_url 代理，平台侧 Python 直连），
        校验 sha256 后解压到 data/plugins/fs/<家庭>/homex.hxcs/integrations/。
        """
        if not self.ha_compat_enabled:
            raise RuntimeError("HA 兼容未启用：请在 HXCS 配置页打开「兼容 HA 插件」")
        registry = self._cfg("registry_url", "")
        package_url = str(payload.get("package_url", ""))
        if not package_url:
            raise RuntimeError("缺少 package_url")
        if package_url.startswith("http://") or package_url.startswith("https://"):
            url = package_url
        else:
            url = registry.rstrip("/") + "/" + package_url
        body = self._http_get(url, max_bytes=64 << 20)
        # sha256 校验（注册表声明的值）
        expect = str(payload.get("expect_sha256", "")).lower()
        if expect:
            got = hashlib.sha256(body).hexdigest()
            if got != expect:
                raise RuntimeError(f"包摘要不匹配：期望 {expect[:16]}… 实际 {got[:16]}…")
        # 解压到持久化目录
        integ_dir = self._integrations_dir()
        if integ_dir is None:
            raise RuntimeError("无法定位集成的持久化目录")
        integ_dir.mkdir(parents=True, exist_ok=True)
        import io, zipfile, tempfile, shutil
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = zf.namelist()
            # zip 根目录下的第一个目录名即集成 domain（HA 约定）
            roots = [n.split("/")[0] for n in names if "/" in n]
            domain = payload.get("domain") or (roots[0] if roots else "integration")
            tmp = Path(tempfile.mkdtemp(prefix="hx-integ-", dir=str(integ_dir)))
            try:
                zf.extractall(tmp)
                src = tmp / domain
                if not src.is_dir():
                    # 兜底：zip 内没有以 domain 命名的目录，取唯一的子目录
                    subs = [d for d in tmp.iterdir() if d.is_dir()]
                    if len(subs) != 1:
                        raise RuntimeError(f"zip 结构无法识别：根下应只有一个目录")
                    src = subs[0]
                # 校验 manifest 存在
                if not (src / "manifest.json").exists():
                    raise RuntimeError("集成包缺少 manifest.json")
                dest = integ_dir / domain
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(src), str(dest))
                # ## 安装即加载（用户 2026-11-01 要求）
                #
                # "安装就应该直接进已安装列表，不需要单独点加载"。
                # 解压完立刻交给运行时注册，配置页的 HA 集成区块直接显示"已加载"，
                # 后续只差 config_flow 配设备。
                loaded = False
                load_error = ""
                if self.runtime is not None:
                    try:
                        self.runtime.install(Path(dest))
                        loaded = True
                    except Exception as e:  # noqa: BLE001
                        load_error = str(e)
                return {
                    "domain": domain, "path": str(dest), "bytes": len(body),
                    "loaded": loaded, "load_error": load_error,
                }
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def op_integration_remove(self, payload: dict[str, Any]) -> dict[str, Any]:
        """卸载 HA 集成：删除已配置的 entry + 从 runtime 摘除 + 删除本地目录。

        用户 2026-11-02：「安装后卡片没有和其他卡片一样显示没有卸载等」。
        社区插件安装后能在已安装列表里停用/卸载，HA 集成也必须有对应入口。
        """
        self._require_ha()
        self._accept_mutation()
        domain = str(payload.get("domain", ""))
        if not domain:
            raise RuntimeError("缺少 domain")
        # ## keep_files：停用 vs 卸载的分界（2026-11-02）
        #
        # 标准卡片的开关语义是"停用"（保留安装，只是不启动），
        # 菜单里的「卸载」才是"删掉"。两者不能共用同一个动作——
        # 否则用户点一下开关就把集成文件删了，装都装不回来。
        #   keep_files=true  → 停用：从 runtime 摘除，本地文件保留
        #   keep_files=false → 卸载：摘除 + 删文件
        keep_files = bool(payload.get("keep_files", False))

        removed_entries = []
        # ① 摘掉该 domain 的所有 config entries
        for entry_id in tuple(self.runtime.entries):
            entry = self.runtime.entries[entry_id]
            if getattr(entry, "domain", None) != domain:
                continue
            removed_entries.append(entry_id)
            self.runtime.entries.pop(entry_id, None)
        # ② 从 runtime.integrations 摘除（不重启 worker 也能立刻失效）
        self.runtime.integrations.pop(domain, None)
        # ③ 卸载才删本地目录；停用保留
        integ_dir = self._integrations_dir()
        target = integ_dir / domain if integ_dir is not None else None
        if not keep_files and target is not None and target.is_dir():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
        return {
            "domain": domain,
            "removed_entries": removed_entries,
            "path_deleted": bool(target and not target.exists()),
            "disabled_only": keep_files,
        }

    def _autoload_integrations(self) -> tuple[list[str], list[str]]:
        """把持久化目录里的集成全部 install 进 runtime。

        HA 的集成是"装了就该能用"——真实 HA 重启后 config entry 自动恢复，
        不需要用户再点一次加载。这里对齐这个语义。
        """
        if self.runtime is None:
            return [], []
        integ_dir = self._integrations_dir()
        if integ_dir is None or not integ_dir.is_dir():
            return [], []
        loaded: list[str] = []
        errors: list[str] = []
        for d in sorted(integ_dir.iterdir()):
            if not (d.is_dir() and (d / "manifest.json").exists()):
                continue
            try:
                pkg = self.runtime.install(d)
                loaded.append(pkg.domain)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{d.name}: {e}")
        return loaded, errors

    def _integrations_dir(self) -> "Path | None":
        """持久化 integrations 目录（跨版本保留）。"""
        ns = getattr(self, "namespace", "")
        try:
            data_plugins = Path.cwd().parents[2]
        except IndexError:
            return None
        if not ns:
            return None
        return data_plugins / "fs" / ns / "homex.hxcs" / "integrations"

    # —— HA 运行时工具（从 HX-Ha_Bridge 移植）———————————————

    def op_load(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.ha_compat_enabled:
            raise RuntimeError("HA 兼容未启用：请在 HXCS 配置页打开「兼容 HA 插件」")
        self._accept_mutation()
        # ## path 可以缺省（2026-11-02）——停用后再启用只需要 domain
        #
        # 前端标准卡片的开关是"启用/停用"，启用时只知道 domain。
        # 这时从持久化目录找 <integrations>/<domain> 即可，不用前端拼路径。
        raw_path = payload.get("path")
        if not raw_path:
            domain = str(payload.get("domain", ""))
            if not domain:
                raise RuntimeError("缺少 path 或 domain")
            integ_dir = self._integrations_dir()
            if integ_dir is None or not (integ_dir / domain).is_dir():
                raise RuntimeError(f"集成 {domain} 不在本地（可能已卸载）")
            raw_path = str(integ_dir / domain)
        package = self.runtime.install(Path(raw_path))
        return {"domain": package.domain, "manifest": package.manifest}

    async def op_config_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        """执行 config_flow 的一步，把 HA 的返回值转成前端可渲染的 JSON。

        # ## 为什么要在 worker 里转（而不是返回原对象）

        HA 的 data_schema 是 voluptuous 的 Schema 对象，里面嵌着
        vol.Required / vol.In / selector 等标记对象 —— json.dumps 直接
        序列化会失败。前端只关心三件事：字段名、控件类型、可选项，
        所以在这里拍平成 [{key, required, type, options, default}]。
        """
        self._require_ha()
        self._accept_mutation()
        # ## input 必须能表达"还没提交"（2026-11-01 实测踩坑）
        #
        # midea 的 async_step_user 写的是 `if user_input is not None:`，
        # 传 {} 会被当成"用户提交了空表单"→ KeyError: 'action'。
        # 这里保证：没有 input 字段时传 None（而不是空 dict）。
        user_input = payload.get("input", None)
        if isinstance(user_input, dict) and not user_input:
            user_input = None
        result = await self.runtime.run_config_flow(
            payload["domain"], user_input, payload.get("step", "user")
        )
        return _flow_result_to_json(result)

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
        # drain 不能崩—— hass 事件循环没起来时 async_block_till_done 会抛异常，
        # 抛了 → Worker 死 → 宿主写响应 broken pipe（用户实测：保存配置后测试连通报此错）。
        if self.runtime:
            try:
                await asyncio.wait_for(self.runtime.hass.async_block_till_done(), timeout=3.0)
            except Exception:
                pass  # 超时/异常都当作已 drain，让代际切换完成
        return {"state": "drained"}

    async def op_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.draining = True
        if self.runtime:
            try:
                for entry_id in tuple(self.runtime.entries):
                    if self.runtime.entries[entry_id].state.value == "loaded":
                        await asyncio.wait_for(self.runtime.async_unload(entry_id), timeout=3.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.runtime.hass.async_block_till_done(), timeout=3.0)
            except Exception:
                pass
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
            self.namespace = str(request["namespace"])
            namespace = str(request["namespace"])
            # 读取配置（平台通过 prepare 传入）
            self.config = request.get("config", {})
            key_hex = os.environ.pop("HX_HA_MASTER_KEY", "")
            # 初始化 HA 运行时（如果需要）
            if len(key_hex) == 64:
                self.runtime = await IntegrationRuntime(root, namespace, bytes.fromhex(key_hex)).start()
            # ## 启动时自动加载已安装的集成（2026-11-01 修复）
            #
            # 事故：装过 Midea AC LAN（已解压到持久化目录），但重启后新
            # worker 的 runtime.integrations 是空的 —— install() 只在
            # integration_install 那一刻调用过。用户点「配置」时
            # run_config_flow 直接 KeyError: 'midea_ac_lan'。
            #
            # 修复：prepare 时扫持久化目录，把每个集成 install 进 runtime。
            # 单个集成加载失败不影响其它（记进 load_errors 供排查）。
            autoloaded, load_errors = self._autoload_integrations()
            return {"generation": self.generation, "state": "prepared",
                    "ha_runtime": self.runtime is not None,
                    "community": self.community_enabled,
                    "autoloaded": autoloaded,
                    "load_errors": load_errors}

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
