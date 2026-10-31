from dataclasses import dataclass
from enum import Enum
from typing import Any
from hx_ha_runtime.entity import Entity

class EntityCategory(str, Enum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"

@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    name: str | None = None
    icon: str | None = None
    entity_category: EntityCategory | None = None

DeviceInfo = dict[str, Any]
