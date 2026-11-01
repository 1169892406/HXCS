"""最小 humidifier 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class HumidifierDeviceClass:
    HUMIDIFIER = "humidifier"
    DEHUMIDIFIER = "dehumidifier"

class HumidifierEntity:
    pass

class HumidifierEntityFeature:
    MODES = "modes"

__all__ = [n for n in dir() if not n.startswith('_')]