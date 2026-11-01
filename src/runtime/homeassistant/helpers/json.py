"""最小 homeassistant.helpers.json 兼容层（转发到 util.json）。"""
from homeassistant.util.json import load_json, save_json  # noqa: F401

__all__ = ["load_json", "save_json"]
