"""EventBusPort — the async pub/sub contract used everywhere.

Backed by NATS+JetStream in production, in-memory in tests. Consumers get a
`Subscription` handle to cancel; producers just await `publish`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from humanoid_robot.events import BaseEvent

EventHandler = Callable[[BaseEvent], Awaitable[None]]


@runtime_checkable
class Subscription(Protocol):
    """A handle to an active subscription."""

    async def cancel(self) -> None: ...


@runtime_checkable
class EventBusPort(Protocol):
    """Publish/subscribe API."""

    async def publish(self, event: BaseEvent) -> None:
        """Publish a single event to its subject."""
        ...

    async def subscribe(
        self,
        subject_pattern: str,
        handler: EventHandler,
        *,
        durable_name: str | None = None,
    ) -> Subscription:
        """Subscribe to events matching a subject pattern.

        `durable_name` (JetStream-specific) makes the subscription resume from
        the last processed message across restarts.
        """
        ...

    async def close(self) -> None:
        """Release resources; safe to call multiple times."""
        ...
