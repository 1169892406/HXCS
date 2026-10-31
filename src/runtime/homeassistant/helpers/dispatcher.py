KEY = "hx_dispatcher"

def async_dispatcher_connect(hass, signal, target):
    listeners = hass.data.setdefault(KEY, {}).setdefault(signal, [])
    listeners.append(target)
    return lambda: listeners.remove(target) if target in listeners else None

def async_dispatcher_send(hass, signal, *args):
    for target in tuple(hass.data.setdefault(KEY, {}).get(signal, [])):
        result = target(*args)
        if hasattr(result, "__await__"): hass.async_create_task(result)
