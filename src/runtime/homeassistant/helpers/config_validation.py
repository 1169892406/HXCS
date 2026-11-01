"""最小 config_validation 兼容层（HXCS HA 运行时）。

真实 Home Assistant 的 helpers.config_validation 有几十个校验器；
HX 集成（midea_ac_lan 等）实际只用到少数几个。这里按需实现，
遇到未实现的名字直接抛出**明确的** AttributeError，
而不是让集成在 import 阶段收到 None 后崩在几百行之外。
"""
from __future__ import annotations

import re
from typing import Any

try:
    import voluptuous as vol
except ImportError:  # pragma: no cover
    vol = None


def string(value: Any) -> str:
    return str(value)


def boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
    raise ValueError(f"无法解析为布尔值: {value!r}")


def positive_int(value: Any) -> int:
    n = int(value)
    if n <= 0:
        raise ValueError(f"必须为正整数: {value!r}")
    return n


def port(value: Any) -> int:
    n = int(value)
    if not 1 <= n <= 65535:
        raise ValueError(f"端口超出范围: {n}")
    return n


def isdevice(value: Any) -> str:
    return str(value)


def entity_id(value: Any) -> str:
    s = str(value)
    if not re.match(r"^[a-z_]+\.[a-z0-9_]+$", s):
        raise ValueError(f"不是合法的 entity_id: {s!r}")
    return s


def time_period_str(value: Any) -> str:
    return str(value)


SCHEMA = vol.Schema if vol else None


__all__ = [
    "boolean", "config_validation", "isdevice", "port", "positive_int",
    "string", "time_period_str", "entity_id", "SCHEMA",
]
