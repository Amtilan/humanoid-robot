"""Tests for the in-memory event bus (also a contract test for EventBusPort)."""

from __future__ import annotations

from typing import ClassVar

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import BaseEvent
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.testing import InMemoryEventBus


class _Ping(BaseEvent):
    subject: ClassVar[str] = "test.ping"
    schema_version: ClassVar[int] = 1

    n: int


class _Pong(BaseEvent):
    subject: ClassVar[str] = "test.pong"
    schema_version: ClassVar[int] = 1

    n: int


def _ev(cls: type[BaseEvent], **fields: object) -> BaseEvent:
    meta = EventMetadata(correlation_id=new_correlation_id(), producer="tests")
    return cls(meta=meta, **fields)


class TestInMemoryEventBus:
    async def test_publish_records_history(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_ev(_Ping, n=1))
        assert len(bus.published) == 1
        assert bus.published[0].subject == "test.ping"

    async def test_direct_subscribe_delivers(self) -> None:
        bus = InMemoryEventBus()
        received: list[BaseEvent] = []

        async def handle(ev: BaseEvent) -> None:
            received.append(ev)

        await bus.subscribe("test.ping", handle)
        await bus.publish(_ev(_Ping, n=1))
        assert len(received) == 1

    async def test_wildcard_star_matches_one_token(self) -> None:
        bus = InMemoryEventBus()
        received: list[BaseEvent] = []

        async def handle(ev: BaseEvent) -> None:
            received.append(ev)

        await bus.subscribe("test.*", handle)
        await bus.publish(_ev(_Ping, n=1))
        await bus.publish(_ev(_Pong, n=1))
        assert len(received) == 2

    async def test_wildcard_gt_matches_rest(self) -> None:
        bus = InMemoryEventBus()
        received: list[BaseEvent] = []

        async def handle(ev: BaseEvent) -> None:
            received.append(ev)

        await bus.subscribe(">", handle)
        await bus.publish(_ev(_Ping, n=1))
        await bus.publish(_ev(_Pong, n=2))
        assert len(received) == 2

    async def test_cancelled_subscription_does_not_receive(self) -> None:
        bus = InMemoryEventBus()
        received: list[BaseEvent] = []

        async def handle(ev: BaseEvent) -> None:
            received.append(ev)

        sub = await bus.subscribe("test.ping", handle)
        await sub.cancel()
        await bus.publish(_ev(_Ping, n=1))
        assert received == []

    async def test_close_prevents_further_publish(self) -> None:
        bus = InMemoryEventBus()
        await bus.close()
        with pytest.raises(RuntimeError, match="closed"):
            await bus.publish(_ev(_Ping, n=1))
