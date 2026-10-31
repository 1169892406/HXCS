from enum import IntFlag

from hx_ha_runtime.entity import Entity

DOMAIN = "cover"
ATTR_POSITION = "position"


class CoverEntityFeature(IntFlag):
    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
    OPEN_TILT = 16
    CLOSE_TILT = 32
    STOP_TILT = 64
    SET_TILT_POSITION = 128


class CoverEntity(Entity):
    pass
