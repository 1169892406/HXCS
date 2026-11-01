"""最小 lock 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class LockEntityFeature:
    OPEN = "open"

class LockEntity:
    pass

class LockEntityState:
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    OPENING = "opening"
    OPEN = "open"

__all__ = [n for n in dir() if not n.startswith('_')]