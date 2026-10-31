from __future__ import annotations

from typing import Any


CAPABILITIES = {
    "sensor": ("read",),
    "binary_sensor": ("read",),
    "switch": ("read", "turn_on", "turn_off"),
    "light": ("read", "turn_on", "turn_off", "brightness"),
    "climate": ("read", "set_hvac_mode", "set_temperature"),
    "cover": ("read", "open_cover", "close_cover", "stop_cover", "set_cover_position"),
    "media_player": ("read", "media_play", "media_pause", "media_stop", "volume_set"),
}


def source_identity(namespace: str, integration: str, entity_id: str) -> str:
    """Stable external identity; display names never participate."""
    return f"ha-integration:{namespace}:{integration}:{entity_id}"


def project_entity(namespace: str, integration: str, state: Any) -> dict[str, Any]:
    domain = state.entity_id.split(".", 1)[0]
    if domain not in CAPABILITIES:
        raise ValueError(f"unsupported entity domain: {domain}")
    capabilities = list(CAPABILITIES[domain])
    if domain == "light":
        attrs = state.attributes
        if attrs.get("supported_color_modes"):
            modes = set(attrs["supported_color_modes"])
            if modes & {"color_temp"}: capabilities.append("color_temperature")
            if modes & {"hs", "rgb", "rgbw", "rgbww", "xy"}: capabilities.append("color")
    return {
        "external_id": source_identity(namespace, integration, state.entity_id),
        "source": "ha-integration-runtime",
        "integration": integration,
        "entity_id": state.entity_id,
        "device_class": state.attributes.get("device_class"),
        "capabilities": capabilities,
        "state": state.state,
        "attributes": dict(state.attributes),
        "available": state.state != "unavailable",
        "context_id": state.context.id if state.context else None,
    }
