"""最小 climate 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class HVACMode:
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    HEAT_COOL = "heat_cool"
    AUTO = "auto"
    DRY = "dry"
    FAN_ONLY = "fan_only"

class ClimateEntity:
    pass

class ClimateEntityFeature:
    TARGET_TEMPERATURE = "target_temperature"
    TARGET_TEMPERATURE_RANGE = "target_temperature_range"
    TARGET_HUMIDITY = "target_humidity"
    FAN_MODE = "fan_mode"
    PRESET_MODE = "preset_mode"
    SWING_MODE = "swing_mode"
    AUX_HEAT = "aux_heat"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"

ATTR_TEMPERATURE = "temperature"
ATTR_HVAC_MODE = "hvac_mode"
ATTR_FAN_MODE = "fan_mode"
ATTR_SWING_MODE = "swing_mode"
ATTR_SWING_HORIZONTAL_MODE = "swing_horizontal_mode"
ATTR_PRESET_MODE = "preset_mode"
DEFAULT_MIN_TEMP = "default_min_temp"
DEFAULT_MAX_TEMP = "default_max_temp"
DEFAULT_MIN_HUMIDITY = "default_min_humidity"
DEFAULT_MAX_HUMIDITY = "default_max_humidity"
__all__ = [n for n in dir() if not n.startswith('_')]