"""最小 media_player 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class MediaPlayerEntity:
    pass

class MediaPlayerEntityFeature:
    pass

class MediaPlayerDeviceClass:
    TV = "tv"
    SPEAKER = "speaker"

__all__ = [n for n in dir() if not n.startswith('_')]