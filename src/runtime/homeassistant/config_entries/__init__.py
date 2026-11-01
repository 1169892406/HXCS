from hx_ha_runtime.flow import ConfigFlow, OptionsFlow
from hx_ha_runtime.models import ConfigEntry, EntryState

# HA 2024.4+ 把 config_flow 的返回值单独起了个名字；就是 dict。
ConfigFlowResult = dict
AbortFlowReason = str

SOURCE_USER = "user"
CONN_CLASS_LOCAL_POLL = "local_poll"
CONN_CLASS_LOCAL_PUSH = "local_push"

__all__ = ["AbortFlowReason", "ConfigEntry", "ConfigFlow", "ConfigFlowResult",
           "EntryState", "OptionsFlow"]
