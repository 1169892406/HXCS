"""最小 fan 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class FanEntityFeature:
    SET_SPEED = "set_speed"
    OSCILLATE = "oscillate"
    DIRECTION = "direction"
    PRESET_MODE = "preset_mode"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"

class FanEntity:
    pass

__all__ = [n for n in dir() if not n.startswith('_')]