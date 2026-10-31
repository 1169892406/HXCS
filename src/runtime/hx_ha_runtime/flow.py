from __future__ import annotations

from typing import Any


class ConfigFlow:
    VERSION = 1

    def __init__(self) -> None:
        self.hass = None
        self.context: dict[str, Any] = {}
        self._unique_id: str | None = None

    async def async_set_unique_id(self, unique_id: str | None = None) -> None:
        self._unique_id = unique_id

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema,
                "errors": errors or {}, "description_placeholders": description_placeholders or {}}

    def async_create_entry(self, *, title: str, data: dict[str, Any], options=None):
        return {"type": "create_entry", "title": title, "data": data, "options": options or {}, "unique_id": self._unique_id}

    def async_abort(self, *, reason: str, description_placeholders=None):
        return {"type": "abort", "reason": reason, "description_placeholders": description_placeholders or {}}


class OptionsFlow(ConfigFlow):
    pass
