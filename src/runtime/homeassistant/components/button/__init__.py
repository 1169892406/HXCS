"""最小 button 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class ButtonEntity:
    pass

class ButtonDeviceClass:
    IDENTIFY = "identify"
    RESTART = "restart"
    UPDATE = "update"

__all__ = [n for n in dir() if not n.startswith('_')]