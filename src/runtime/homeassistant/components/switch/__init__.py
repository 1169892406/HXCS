"""最小 switch 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class SwitchDeviceClass:
    OUTLET = "outlet"
    LIGHT = "light"
    SWITCH = "switch"
    PLUG = "plug"

class SwitchEntity:
    pass

__all__ = [n for n in dir() if not n.startswith('_')]