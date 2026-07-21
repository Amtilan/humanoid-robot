"""Relay: ``wall.command.requested`` events → wall agent → result events.

Both the voice intent module (in cortex-rag) and the operator dashboard
publish ``WallCommandRequested``; this relay is the single component that
actually talks to the wall agent, so every command — whatever its source —
flows through one place, gets executed once, and leaves an audit trail
(both subjects are recorded by the safety audit log).
"""

from __future__ import annotations

import logging

from humanoid_robot.events import WallCommandRequested, WallCommandResulted
from humanoid_robot.events.base import BaseEvent, EventMetadata
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.ports.wall import WallControlPort

log = logging.getLogger(__name__)


class WallCommandRelay:
    """Executes requested wall commands and reports their outcome."""

    def __init__(self, *, bus: EventBusPort, wall: WallControlPort) -> None:
        self._bus = bus
        self._wall = wall
        self._subscription: Subscription | None = None

    async def start(self) -> None:
        self._subscription = await self._bus.subscribe(
            WallCommandRequested.subject, self._on_requested
        )

    async def stop(self) -> None:
        if self._subscription is not None:
            await self._subscription.cancel()
            self._subscription = None
        await self._wall.close()

    async def _on_requested(self, event: BaseEvent) -> None:
        if not isinstance(event, WallCommandRequested):
            return
        result = await self._wall.send(event.command)
        log.info(
            "wall command %s (%s from %s) -> %s %s",
            event.command_id,
            event.command.section or event.command.nav,
            event.source,
            result.outcome.value,
            result.detail,
        )
        await self._bus.publish(
            WallCommandResulted(
                meta=EventMetadata(
                    correlation_id=event.meta.correlation_id,
                    causation_id=event.meta.event_id,
                    producer="cortex-core.wall_relay",
                ),
                command_id=event.command_id,
                result=result,
            )
        )
