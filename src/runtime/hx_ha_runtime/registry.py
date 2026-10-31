from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import DeviceRecord, EntityRecord


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return value or "entity"


class RegistryStore:
    def __init__(self, path: Path, namespace: str) -> None:
        self.path, self.namespace = path, namespace
        self.entities: dict[str, EntityRecord] = {}
        self.devices: dict[str, DeviceRecord] = {}
        self._entity_keys: dict[tuple[str, str, str], str] = {}
        self._device_keys: dict[tuple[str, str], str] = {}
        self._load()

    def _stable_id(self, kind: str, key: str) -> str:
        return hashlib.sha256(f"{self.namespace}:{kind}:{key}".encode()).hexdigest()[:24]

    def get_or_create_entity(self, *, domain: str, platform: str, unique_id: str,
                             config_entry_id: str, suggested_object_id: str | None = None,
                             name: str | None = None, device_id: str | None = None) -> EntityRecord:
        key = (platform, domain, unique_id)
        if key in self._entity_keys:
            return self.entities[self._entity_keys[key]]
        base = _slug(suggested_object_id or name or unique_id)
        entity_id, suffix = f"{domain}.{base}", 2
        while entity_id in self.entities:
            entity_id, suffix = f"{domain}.{base}_{suffix}", suffix + 1
        record = EntityRecord(entity_id, unique_id, platform, domain, config_entry_id, name, False, device_id)
        self.entities[entity_id] = record
        self._entity_keys[key] = entity_id
        self.save()
        return record

    def get_or_create_device(self, *, identifiers=(), connections=(), config_entry_id: str,
                             **info: Any) -> DeviceRecord:
        ids, conns = set(map(tuple, identifiers)), set(map(tuple, connections))
        matches = [self._device_keys[key] for key in ids | conns if key in self._device_keys]
        if matches:
            record = self.devices[matches[0]]
        else:
            identity = sorted(ids or conns)
            record = DeviceRecord(self._stable_id("device", repr(identity)))
            self.devices[record.id] = record
        record.identifiers |= ids
        record.connections |= conns
        record.config_entries.add(config_entry_id)
        for key in ids | conns:
            self._device_keys[key] = record.id
        for field in ("manufacturer", "model", "name", "sw_version", "hw_version", "serial_number"):
            if info.get(field) is not None:
                setattr(record, field, info[field])
        self.save()
        return record

    def remove_config_entry(self, entry_id: str) -> set[str]:
        """Remove entry-owned entities and orphan devices; return removed entity ids."""
        removed = {entity_id for entity_id, record in self.entities.items()
                   if record.config_entry_id == entry_id}
        for entity_id in removed:
            record = self.entities.pop(entity_id)
            self._entity_keys.pop((record.platform, record.domain, record.unique_id), None)
        for device_id, device in list(self.devices.items()):
            device.config_entries.discard(entry_id)
            if not device.config_entries:
                self.devices.pop(device_id)
                for key in device.identifiers | device.connections:
                    if self._device_keys.get(key) == device_id:
                        self._device_keys.pop(key, None)
        self.save()
        return removed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "namespace": self.namespace,
            "entities": [asdict(e) for e in self.entities.values()],
            "devices": [{**asdict(d), "identifiers": sorted(d.identifiers), "connections": sorted(d.connections),
                         "config_entries": sorted(d.config_entries)} for d in self.devices.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("namespace") != self.namespace:
            raise ValueError("registry namespace mismatch")
        for raw in data.get("entities", []):
            record = EntityRecord(**raw)
            self.entities[record.entity_id] = record
            self._entity_keys[(record.platform, record.domain, record.unique_id)] = record.entity_id
        for raw in data.get("devices", []):
            raw["identifiers"] = set(map(tuple, raw["identifiers"]))
            raw["connections"] = set(map(tuple, raw["connections"]))
            raw["config_entries"] = set(raw["config_entries"])
            record = DeviceRecord(**raw)
            self.devices[record.id] = record
            for key in record.identifiers | record.connections:
                self._device_keys[key] = record.id
