"""最小 water_heater 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class WaterHeaterEntity:
    pass

class WaterHeaterEntityFeature:
    TARGET_TEMPERATURE = "target_temperature"
    OPERATION_MODE = "operation_mode"
    AWAY_MODE = "away_mode"
    ON_OFF = "on_off"

__all__ = [n for n in dir() if not n.startswith('_')]