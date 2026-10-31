def async_get_clientsession(hass):
    """Return the HOMEX-controlled deny-by-default network session."""
    return hass.data["hx_http_session"]
