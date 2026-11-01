"""最小 time 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class TimeEntity:
    pass

__all__ = [n for n in dir() if not n.startswith('_')]