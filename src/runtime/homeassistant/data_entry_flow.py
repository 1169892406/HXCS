"""最小 homeassistant.data_entry_flow 兼容层。"""
from __future__ import annotations

RESULT_TYPE_FORM = "form"
RESULT_TYPE_CREATE_ENTRY = "create_entry"
RESULT_TYPE_ABORT = "abort"
RESULT_TYPE_SHOW_PROGRESS = "progress"
RESULT_TYPE_EXTERNAL_STEP = "external"
RESULT_TYPE_EXTERNAL_STEP_DONE = "external_done"

FLOW_DIRECTION_IMPORT = "import"


class FlowHandler:
    """占位基类：集成极少直接继承它（走 ConfigFlow 即可）。"""


class FlowResult(dict):
    """HA 的 FlowResult 就是 dict 的子类别名。"""


__all__ = [n for n in dir() if n.isupper() or n in ("FlowHandler", "FlowResult")]
