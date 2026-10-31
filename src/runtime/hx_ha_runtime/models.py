from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EntryState(str, Enum):
    NOT_LOADED = "not_loaded"
    LOADED = "loaded"
    SETUP_ERROR = "setup_error"


@dataclass(slots=True)
class Context:
    id: str
    parent_id: str | None = None


@dataclass(slots=True)
class State:
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_updated: datetime
    context: Context | None = None


@dataclass(slots=True)
class ConfigEntry:
    domain: str
    title: str
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)
    entry_id: str = ""
    unique_id: str | None = None
    state: EntryState = EntryState.NOT_LOADED
    _listeners: list[Any] = field(default_factory=list, repr=False)
    _runtime_data: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    @property
    def runtime_data(self) -> dict[str, Any]:
        """Ephemeral setup-only view containing public data and decrypted credentials."""
        return self._runtime_data if self._runtime_data is not None else self.data

    def add_update_listener(self, listener: Any):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    async def notify_update(self, hass: Any) -> None:
        for listener in tuple(self._listeners):
            result = listener(hass, self)
            if hasattr(result, "__await__"):
                await result


@dataclass(slots=True)
class EntityRecord:
    entity_id: str
    unique_id: str
    platform: str
    domain: str
    config_entry_id: str
    name: str | None = None
    disabled: bool = False
    device_id: str | None = None


@dataclass(slots=True)
class DeviceRecord:
    id: str
    identifiers: set[tuple[str, str]] = field(default_factory=set)
    connections: set[tuple[str, str]] = field(default_factory=set)
    manufacturer: str | None = None
    model: str | None = None
    name: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    serial_number: str | None = None
    config_entries: set[str] = field(default_factory=set)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
