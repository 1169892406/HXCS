"""最小 homeassistant.helpers.typing 兼容层。"""
from __future__ import annotations

from typing import Any, TypeVar

ConfigType = dict[str, Any]
DiscoveryInfoType = dict[str, Any]
StateType = str | int | float | None
ServiceDataType = dict[str, Any]

__all__ = ["ConfigType", "DiscoveryInfoType", "StateType", "ServiceDataType"]
