"""最小 homeassistant.helpers.selector 兼容层。

HA 的 selector 是用来**声明表单控件类型**的（文本/密码/下拉/数字…），
前端按它渲染。HXCS 的配置页拿到 data_schema 后自己渲染，
所以这里只要能构造对象 + 保留类型信息即可。

关键点：`TextSelectorConfig(type=TextSelectorType.PASSWORD)` 这类调用
必须能原样保存下来，供前端判断"这个字段是密码框"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SelectorType:
    """selector 类型常量。"""


class TextSelectorType:
    EMAIL = "email"
    PASSWORD = "password"
    TEL = "tel"
    TEXT = "text"
    URL = "url"


@dataclass
class TextSelectorConfig:
    type: str = TextSelectorType.TEXT
    multiline: bool = False
    suffix: str | None = None
    prefix: str | None = None
    autocomplete: str | None = None
    multiple: bool = False


@dataclass
class SelectSelectorConfig:
    options: list[Any] = field(default_factory=list)
    multiple: bool = False
    mode: str | None = None
    translation_key: str | None = None


@dataclass
class NumberSelectorConfig:
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit_of_measurement: str | None = None
    mode: str | None = None


@dataclass
class BooleanSelectorConfig:
    pass


@dataclass
class SelectSelectorOption:
    value: str
    label: str | None = None


class Selector:
    """基础 Selector：把 config 原样挂上去。"""

    def __init__(self, config: Any = None) -> None:
        self.config = config

    def __repr__(self) -> str:
        return f"Selector({self.config!r})"

    def as_selector(self) -> dict[str, Any]:
        """序列化成前端可读的形状（HXCS 配置页用）。"""
        return {"config": self.config.__dict__ if hasattr(self.config, "__dict__") else self.config}


class TextSelector(Selector):
    def __init__(self, config: TextSelectorConfig | None = None) -> None:
        super().__init__(config or TextSelectorConfig())


class SelectSelector(Selector):
    def __init__(self, config: SelectSelectorConfig | None = None) -> None:
        super().__init__(config or SelectSelectorConfig())


class NumberSelector(Selector):
    def __init__(self, config: NumberSelectorConfig | None = None) -> None:
        super().__init__(config or NumberSelectorConfig())


class BooleanSelector(Selector):
    def __init__(self, config: BooleanSelectorConfig | None = None) -> None:
        super().__init__(config or BooleanSelectorConfig())


__all__ = [
    "BooleanSelector", "BooleanSelectorConfig", "NumberSelector",
    "NumberSelectorConfig", "SelectSelector", "SelectSelectorConfig",
    "SelectSelectorOption", "Selector", "SelectorType", "TextSelector",
    "TextSelectorConfig", "TextSelectorType",
]
