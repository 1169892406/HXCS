"""最小 select 组件兼容层（HXCS HA 运行时）。"""
from __future__ import annotations

class SelectEntity:
    pass

class SelectEntityDescription:
    pass

__all__ = [n for n in dir() if not n.startswith('_')]