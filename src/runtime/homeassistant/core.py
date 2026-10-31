from hx_ha_runtime.core import HomeAssistant
from hx_ha_runtime.models import Context, State

def callback(func):
    return func

__all__ = ["Context", "HomeAssistant", "State", "callback"]
