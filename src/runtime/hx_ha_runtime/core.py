from __future__ import annotations

import asyncio
import inspect
import uuid
from collections import defaultdict
from typing import Any, Awaitable, Callable

from .models import Context, State, utcnow


class EventBus:
    ALLOWED = {"homeassistant_start", "homeassistant_stop", "state_changed", "call_service"}

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def async_listen(self, event_type: str, listener: Callable):
        if event_type not in self.ALLOWED:
            raise ValueError(f"event not allowed: {event_type}")
        self._listeners[event_type].append(listener)
        return lambda: self._listeners[event_type].remove(listener) if listener in self._listeners[event_type] else None

    async def async_fire(self, event_type: str, event_data: dict[str, Any] | None = None, context: Context | None = None):
        event = type("Event", (), {"event_type": event_type, "data": event_data or {}, "context": context})()
        for listener in tuple(self._listeners[event_type]):
            result = listener(event)
            if inspect.isawaitable(result):
                await result


class StateMachine:
    def __init__(self, bus: EventBus, projector: Callable[[State | None], Any] | None = None) -> None:
        self._states: dict[str, State] = {}
        self._bus, self._projector = bus, projector

    def get(self, entity_id: str) -> State | None:
        return self._states.get(entity_id)

    def async_all(self) -> list[State]:
        return list(self._states.values())

    async def async_set(self, entity_id: str, new_state: Any, attributes: dict[str, Any] | None = None,
                        context: Context | None = None) -> None:
        now, old = utcnow(), self._states.get(entity_id)
        state_text = str(new_state).lower() if isinstance(new_state, bool) else str(new_state)
        changed = old is None or old.state != state_text
        state = State(entity_id, state_text, dict(attributes or {}), now if changed else old.last_changed, now, context)
        self._states[entity_id] = state
        await self._bus.async_fire("state_changed", {"entity_id": entity_id, "old_state": old, "new_state": state}, context)
        if self._projector:
            result = self._projector(state)
            if inspect.isawaitable(result):
                await result

    async def async_remove(self, entity_id: str, context: Context | None = None) -> bool:
        old = self._states.pop(entity_id, None)
        if old is None:
            return False
        await self._bus.async_fire("state_changed", {"entity_id": entity_id, "old_state": old, "new_state": None}, context)
        if self._projector:
            result = self._projector(None)
            if inspect.isawaitable(result):
                await result
        return True


class ServiceRegistry:
    def __init__(self, bus: EventBus) -> None:
        self._services: dict[tuple[str, str], tuple[Callable, Callable | None]] = {}
        self._bus = bus

    def async_register(self, domain: str, service: str, handler: Callable, schema: Callable | None = None) -> None:
        self._services[(domain, service)] = (handler, schema)

    def async_remove(self, domain: str, service: str) -> bool:
        return self._services.pop((domain, service), None) is not None

    async def async_call(self, domain: str, service: str, service_data: dict[str, Any] | None = None,
                         blocking: bool = False, context: Context | None = None, timeout: float = 10) -> Any:
        if (domain, service) not in self._services:
            raise ValueError(f"service not found: {domain}.{service}")
        handler, schema = self._services[(domain, service)]
        data = schema(service_data or {}) if schema else dict(service_data or {})
        context = context or Context(str(uuid.uuid4()))
        call = type("ServiceCall", (), {"domain": domain, "service": service, "data": data, "context": context})()
        await self._bus.async_fire("call_service", {"domain": domain, "service": service, "service_data": data}, context)
        async def invoke():
            result = handler(call)
            return await result if inspect.isawaitable(result) else result
        task = asyncio.create_task(invoke())
        if blocking:
            return await asyncio.wait_for(task, timeout)
        return task


class _HassConfig:
    """HA 的 `hass.config` 在 HOMEX 里的替身（2026-11-09）。

    # 它补的是什么

    集成广泛使用 `self.hass.config.path("...")` 来定位自己的存储目录（midea
    的 device 缓存、配置缓存都是这么写的）。此前 HA 兼容层的 HomeAssistant
    没有 `config` 属性 ⇒ `AttributeError: 'HomeAssistant' object has no
    attribute 'config'` —— 用户的配置流程走到"选设备"那一步必然崩。

    # path() 映射到哪

    映射到**本插件在本家庭的持久化目录**（IntegrationRuntime.root），
    并自动建好父目录。三条理由：
      · 集成要的是"一个可写且重启后还在的地方"，这正是 root 的语义；
      · 不该给集成宿主的任意路径（那是沙箱逃逸）；
      · 建父目录而不是要求集成自己建：HA 原生的 config/.storage 已经存在，
        集成写文件时不会先 mkdir —— 让它改代码是给作者添负担。

    # 为什么只实现 path / config_dir

    这三个是集成最常用的（`path`、`config_dir`、以及直接拼路径）。`time_zone`
    之类先给一个稳定值：midea 只读它做日志时间戳，缺省会崩在无关的地方。
    """

    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir
        # 与 HA 一致：默认时区取部署常识值。集成只用来做本地时间显示，
        # 猜错不影响功能（我们的日志用 UTC）。
        self.time_zone = "Asia/Shanghai"
        self.latitude = 0.0
        self.longitude = 0.0
        self.elevation = 0
        self.units = None
        self.language = "zh-Hans"

    def path(self, *parts: str) -> str:
        """拼出 config_dir 之下的绝对路径，并**建好父目录**。"""
        import os as _os
        target = _os.path.join(self.config_dir, *[str(p) for p in parts if p])
        parent = _os.path.dirname(target)
        try:
            if parent:
                _os.makedirs(parent, exist_ok=True)
        except OSError:
            # 建不出来不在这里炸：集成会在真正写文件时报出可读的错误，
            # 比在这里抛一个"path() 失败"更容易定位。
            pass
        return target


class HomeAssistant:
    def __init__(self, *, projector=None) -> None:
        self.bus = EventBus()
        self.states = StateMachine(self.bus, projector)
        self.services = ServiceRegistry(self.bus)
        self.data: dict[str, Any] = {}
        self.loop = asyncio.get_running_loop()
        self.config_entries: Any = None
        # config 由 start() 按 runtime.root 装上（见 IntegrationRuntime.start）。
        self.config: Any = None
        self._tasks: set[asyncio.Task] = set()

    def async_create_task(self, target: Awaitable, name: str | None = None) -> asyncio.Task:
        task = self.loop.create_task(target, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def async_add_executor_job(self, target: Callable, *args: Any) -> Any:
        return await self.loop.run_in_executor(None, target, *args)

    async def async_block_till_done(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
