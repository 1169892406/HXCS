from __future__ import annotations
import inspect
from datetime import timedelta
from hx_ha_runtime.entity import Entity

class UpdateFailed(Exception): pass

class DataUpdateCoordinator:
    def __init__(self, hass, logger=None, *, name=None, update_interval: timedelta | None = None, update_method=None):
        self.hass, self.name, self.update_interval, self.update_method = hass, name, update_interval, update_method
        self.data = None
        self.last_update_success = True
        self._listeners = []
    def async_add_listener(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None
    async def async_refresh(self):
        try:
            result = self.update_method() if self.update_method else await self._async_update_data()
            self.data = await result if inspect.isawaitable(result) else result
            self.last_update_success = True
        except Exception:
            self.last_update_success = False
            raise
        for listener in tuple(self._listeners): listener()
    async def async_config_entry_first_refresh(self): await self.async_refresh()
    async def _async_update_data(self): raise NotImplementedError

class CoordinatorEntity(Entity):
    _attr_should_poll = False
    def __init__(self, coordinator):
        self.coordinator = coordinator
    @property
    def available(self): return self.coordinator.last_update_success
    async def async_added_to_hass(self):
        self._remove_listener = self.coordinator.async_add_listener(self.async_schedule_update_ha_state)
    async def async_will_remove_from_hass(self):
        if hasattr(self, "_remove_listener"): self._remove_listener()
