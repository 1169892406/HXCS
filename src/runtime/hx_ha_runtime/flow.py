from __future__ import annotations

from typing import Any


class AbortFlow(Exception):
    """config_flow 主动终止（对应 HA 的 AbortFlow 异常）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ConfigFlow:
    VERSION = 1

    # ## 必须接受 domain= 关键字（HA 的集成都这么写）
    #
    # 集成声明的写法是 `class MideaLanConfigFlow(ConfigFlow, domain=DOMAIN):`，
    # 靠 __init_subclass__ 捕获 domain。不支持就会在**类定义**阶段就
    # TypeError（不是运行期），表现为"集成整个 import 不了"。
    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.DOMAIN = domain

    def __init__(self) -> None:
        self.hass = None
        self.context: dict[str, Any] = {}
        self._unique_id: str | None = None

    async def async_set_unique_id(self, unique_id: str | None = None) -> None:
        self._unique_id = unique_id

    # ## HA 集成常用的几个查询辅助（2026-11-01 实测）
    #
    # 集成写 `self._async_current_entries()` 去判断"这个设备是不是已经配过"。
    # 真实 HA 里这些是 ConfigFlow 的内建方法；兼容层没有就会在运行期
    # AttributeError（midea 就是在 _device_configured 里用的）。
    def _async_current_entries(self):
        """当前 domain 已存在的 config entries（用于去重校验）。"""
        entries = getattr(self.hass, "_config_entries", None) if self.hass else None
        if entries is None:
            return []
        domain = getattr(type(self), "DOMAIN", None) or getattr(self, "DOMAIN", None)
        return [e for e in entries.values() if getattr(e, "domain", None) == domain]

    def _async_has_entries(self) -> bool:
        return bool(self._async_current_entries())

    def async_abort_entries_match(self, other_entries_match: dict | None = None) -> None:
        """已有同 unique_id 的 entry 则终止流程。

        HA 的真实实现会抛 AbortFlow 让上层返回 abort 结果。
        兼容层里"抛"由 run_config_flow 的 try 捕获并转成 abort。
        """
        entries = self._async_current_entries()
        if not entries:
            return
        if other_entries_match is None:
            if any(getattr(e, "unique_id", None) == self._unique_id for e in entries):
                raise AbortFlow("already_configured")
            return
        for e in entries:
            data = getattr(e, "data", {}) or {}
            if all(data.get(k) == v for k, v in other_entries_match.items()):
                raise AbortFlow("already_configured")

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema,
                "errors": errors or {}, "description_placeholders": description_placeholders or {}}

    def async_create_entry(self, *, title: str, data: dict[str, Any], options=None):
        return {"type": "create_entry", "title": title, "data": data, "options": options or {}, "unique_id": self._unique_id}

    def async_abort(self, *, reason: str, description_placeholders=None):
        return {"type": "abort", "reason": reason, "description_placeholders": description_placeholders or {}}


class OptionsFlow(ConfigFlow):
    pass
