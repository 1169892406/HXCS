from hx_ha_runtime.core import HomeAssistant
from hx_ha_runtime.models import Context, Event, State

def callback(func):
    return func

__all__ = ["Context", "Event", "HomeAssistant", "State", "callback"]
