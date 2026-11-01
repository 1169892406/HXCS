"""最小 homeassistant.const 兼容层。

只定义集成实际 import 的常量。真实 HA 有几百个；缺的那个会以明确的
ImportError（cannot import name 'X'）暴露出来，补一行即可。

## 为什么不一次性抄全
抄全会让这个文件变成一个"看起来像 HA 但没有实现"的空壳，
下次缺符号时更难分辨"是真的不支持还是抄漏了"。按需补、
每次补都只加真实被引用的名字。
"""
from __future__ import annotations

# ── 版本（集成用它走 feature 分支）──────────────────────────
MAJOR_VERSION = 2026
MINOR_VERSION = 10
PATCH_VERSION = "0"

# ── 配置键 ───────────────────────────────────────────────────
CONF_CUSTOMIZE = "customize"
CONF_DEVICE = "device"
CONF_DEVICE_ID = "device_id"
CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"
CONF_PASSWORD = "password"
CONF_PORT = "port"
CONF_PROTOCOL = "protocol"
CONF_SENSORS = "sensors"
CONF_SWITCHES = "switches"
CONF_TOKEN = "token"
CONF_TYPE = "type"
CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_ENTRY_ID = "entry_id"
CONF_UNIQUE_ID = "unique_id"

# ── 属性 ─────────────────────────────────────────────────────
ATTR_TEMPERATURE = "temperature"
ATTR_HVAC_MODE = "hvac_mode"
ATTR_FAN_MODE = "fan_mode"
ATTR_SWING_MODE = "swing_mode"

# ── 事件 ─────────────────────────────────────────────────────
EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
EVENT_HOMEASSISTANT_START = "homeassistant_start"
EVENT_STATE_CHANGED = "state_changed"

# ── 单位 ─────────────────────────────────────────────────────
PERCENTAGE = "%"
CONCENTRATION_MICROGRAMS_PER_CUBIC_METER = "µg/m³"
CONCENTRATION_PARTS_PER_MILLION = "ppm"
REVOLUTIONS_PER_MINUTE = "rpm"
TEMP_CELSIUS = "°C"
TEMP_FAHRENHEIT = "°F"
POWER_WATT = "W"
ENERGY_KILO_WATT_HOUR = "kWh"

# ── 精度 ─────────────────────────────────────────────────────
PRECISION_HALVES = 0.5
PRECISION_TENTHS = 0.1
PRECISION_WHOLE = 1.0

# ── 状态 ─────────────────────────────────────────────────────
STATE_ON = "on"
STATE_OFF = "off"
STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"

# ── 平台 ─────────────────────────────────────────────────────
class Platform:
    AIR_QUALITY = "air_quality"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CLIMATE = "climate"
    COVER = "cover"
    FAN = "fan"
    HUMIDIFIER = "humidifier"
    LIGHT = "light"
    LOCK = "lock"
    MEDIA_PLAYER = "media_player"
    NUMBER = "number"
    REMOTE = "remote"
    SELECT = "select"
    SENSOR = "sensor"
    SWITCH = "switch"
    TIME = "time"
    VACUUM = "vacuum"
    WATER_HEATER = "water_heater"

__all__ = [n for n in dir() if n.isupper() or n == "Platform"]

# ── 单位枚举（HA 2024+ 把单位改成 StrEnum）───────────────────────
class UnitOfDensity:
    GRAMS_PER_CUBIC_METER = "g/m³"
    MICROGRAMS_PER_CUBIC_METER = "µg/m³"
    MILLIGRAMS_PER_CUBIC_METER = "mg/m³"


class UnitOfElectricCurrent:
    AMPERE = "A"
    MILLIAMPERE = "mA"


class UnitOfElectricPotential:
    VOLT = "V"
    MILLIVOLT = "mV"


class UnitOfEnergy:
    KILO_WATT_HOUR = "kWh"
    WATT_HOUR = "Wh"
    MEGA_WATT_HOUR = "MWh"


class UnitOfFrequency:
    HERTZ = "Hz"
    KILOHERTZ = "kHz"
    MEGAHERTZ = "MHz"
    GIGAHERTZ = "GHz"


class UnitOfPower:
    WATT = "W"
    KILO_WATT = "kW"
    MEGA_WATT = "MW"


class UnitOfPressure:
    PASCAL = "Pa"
    HECTO_PASCAL = "hPa"
    KILO_PASCAL = "kPa"
    KPA = "kPa"
    MILLIBAR = "mbar"
    BAR = "bar"


class UnitOfRatio:
    PERCENT = "%"
    PARTS_PER_MILLION = "ppm"


class UnitOfTemperature:
    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class UnitOfTime:
    SECONDS = "s"
    MINUTES = "min"
    HOURS = "h"
    DAYS = "d"
    MONTHS = "mo"


class UnitOfVolume:
    LITERS = "L"
    MILLILITERS = "mL"
    CUBIC_METERS = "m³"


class UnitOfVolumeFlowRate:
    CUBIC_METERS_PER_HOUR = "m³/h"
    LITERS_PER_HOUR = "L/h"
    LITERS_PER_MINUTE = "L/min"
    LITERS_PER_SECOND = "L/s"


__all__ = [n for n in dir() if n.isupper() or n.startswith("UnitOf") or n == "Platform"]
