"""最小 light 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class LightEntityFeature:
    EFFECT = "effect"
    FLASH = "flash"
    TRANSITION = "transition"

class ColorMode:
    ONOFF = "onoff"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"
    HS = "hs"
    XY = "xy"
    RGB = "rgb"
    RGBW = "rgbw"
    RGBWW = "rgbww"
    WHITE = "white"

class LightEntity:
    pass

__all__ = [n for n in dir() if not n.startswith('_')]