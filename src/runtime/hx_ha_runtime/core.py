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


class HomeAssistant:
    def __init__(self, *, projector=None) -> None:
        self.bus = EventBus()
        self.states = StateMachine(self.bus, projector)
        self.services = ServiceRegistry(self.bus)
        self.data: dict[str, Any] = {}
        self.loop = asyncio.get_running_loop()
        self.config_entries: Any = None
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
