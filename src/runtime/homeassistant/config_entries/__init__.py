from hx_ha_runtime.flow import ConfigFlow, OptionsFlow
from hx_ha_runtime.models import ConfigEntry, EntryState

SOURCE_USER = "user"
CONN_CLASS_LOCAL_POLL = "local_poll"
CONN_CLASS_LOCAL_PUSH = "local_push"

__all__ = ["ConfigEntry", "ConfigFlow", "OptionsFlow", "EntryState"]
