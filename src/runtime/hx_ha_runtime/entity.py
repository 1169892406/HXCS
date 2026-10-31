from __future__ import annotations

import inspect
from typing import Any, Iterable

SUPPORTED_DOMAINS = {"sensor", "binary_sensor", "switch", "light", "climate", "cover", "media_player"}


class Entity:
    _attr_available = True
    _attr_should_poll = True
    _attr_name: str | None = None
    _attr_unique_id: str | None = None

    @property
    def unique_id(self): return self._attr_unique_id
    @property
    def name(self): return self._attr_name
    @property
    def available(self): return self._attr_available
    @property
    def should_poll(self): return self._attr_should_poll
    @property
    def extra_state_attributes(self): return None
    @property
    def device_info(self): return None
    @property
    def state(self): return None

    async def async_added_to_hass(self): pass
    async def async_will_remove_from_hass(self): pass
    async def async_update(self): pass

    async def async_write_ha_state(self):
        if not self.hass or not self.entity_id:
            return
        state, attrs = entity_state(self)
        if not self.available:
            state = "unavailable"
        await self.hass.states.async_set(self.entity_id, state, attrs)

    def async_schedule_update_ha_state(self, force_refresh=False):
        async def update():
            if force_refresh:
                await self.async_update()
            await self.async_write_ha_state()
        return self.hass.async_create_task(update())


def entity_state(entity: Entity) -> tuple[Any, dict[str, Any]]:
    attrs = dict(entity.extra_state_attributes or {})
    domain = entity.entity_id.split(".", 1)[0]
    if domain == "binary_sensor":
        value = "on" if getattr(entity, "is_on", False) else "off"
    elif domain in {"switch", "light"}:
        value = "on" if getattr(entity, "is_on", False) else "off"
        if domain == "light":
            for field in ("brightness", "color_temp", "hs_color", "rgb_color", "supported_color_modes"):
                value_attr = getattr(entity, field, None)
                if value_attr is not None:
                    attrs[field] = value_attr
    elif domain == "climate":
        value = getattr(entity, "hvac_mode", None)
        for field in ("current_temperature", "target_temperature", "target_temperature_high",
                      "target_temperature_low", "hvac_modes", "fan_mode", "fan_modes",
                      "preset_mode", "preset_modes", "swing_mode", "swing_modes",
                      "current_humidity", "target_humidity", "supported_features"):
            value_attr = getattr(entity, field, None)
            if value_attr is not None:
                attrs[field] = value_attr
    elif domain == "cover":
        if getattr(entity, "is_opening", False):
            value = "opening"
        elif getattr(entity, "is_closing", False):
            value = "closing"
        elif getattr(entity, "is_closed", None) is True:
            value = "closed"
        else:
            value = "open"
        for field in ("current_cover_position", "current_cover_tilt_position", "supported_features"):
            value_attr = getattr(entity, field, None)
            if value_attr is not None:
                attrs[field.removeprefix("current_cover_")] = value_attr
    elif domain == "media_player":
        value = getattr(entity, "state", None)
        for field in ("volume_level", "is_volume_muted", "media_content_id", "media_content_type",
                      "media_duration", "media_position", "media_title", "media_artist",
                      "media_album_name", "source", "source_list", "sound_mode", "sound_mode_list",
                      "supported_features"):
            value_attr = getattr(entity, field, None)
            if value_attr is not None:
                attrs[field] = value_attr
    else:
        value = getattr(entity, "native_value", entity.state)
        for field in ("native_unit_of_measurement", "device_class", "state_class"):
            value_attr = getattr(entity, field, None)
            if value_attr is not None:
                attrs[field.removeprefix("native_")] = value_attr
    return value if value is not None else "unknown", attrs


class EntityPlatform:
    def __init__(self, hass, registry, config_entry, domain: str) -> None:
        if domain not in SUPPORTED_DOMAINS:
            raise ValueError(f"unsupported entity platform: {domain}")
        self.hass, self.registry, self.config_entry, self.domain = hass, registry, config_entry, domain
        self.entities: dict[str, Entity] = {}

    async def async_add_entities(self, new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        for entity in new_entities:
            unique_id = entity.unique_id
            if not unique_id:
                raise ValueError("entity unique_id is required")
            device_id = None
            if entity.device_info:
                device = self.registry.get_or_create_device(
                    config_entry_id=self.config_entry.entry_id, **dict(entity.device_info))
                device_id = device.id
            record = self.registry.get_or_create_entity(
                domain=self.domain, platform=self.config_entry.domain, unique_id=str(unique_id),
                config_entry_id=self.config_entry.entry_id, suggested_object_id=entity.name,
                name=entity.name, device_id=device_id)
            entity.hass, entity.entity_id = self.hass, record.entity_id
            self.entities[record.entity_id] = entity
            if update_before_add:
                await entity.async_update()
            await entity.async_added_to_hass()
            await entity.async_write_ha_state()

    async def async_remove(self) -> None:
        for entity in tuple(self.entities.values()):
            await entity.async_will_remove_from_hass()
            await self.hass.states.async_remove(entity.entity_id)
        self.entities.clear()
