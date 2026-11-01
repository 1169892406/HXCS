"""最小 homeassistant.components.diagnostics 兼容层（无诊断导出）。"""
from __future__ import annotations


def async_redact_data(data, redact_keys):
    return {k: "**REDACTED**" if k in redact_keys else v for k, v in data.items()}


__all__ = ["async_redact_data"]
