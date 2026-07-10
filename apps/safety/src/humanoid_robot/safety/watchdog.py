"""SafetyWatchdog — auto-engage e-stop when operator liveness expires.

Runs as a background task: subscribes to ``safety.watchdog.heartbeat``,
keeps the last-seen monotonic timestamp, and every ``check_interval_s``
checks whether ``timeout_s`` has elapsed since the last heartbeat.  On
expiry it asks the ``SafetyGate`` to engage the e-stop, tagging the
engagement with actor ``watchdog`` and reason ``no heartbeat``.

Fail-closed by design: the watchdog considers itself expired at boot
until the first heartbeat lands — but it does NOT engage on this
initial state (the container already boots with e-stop engaged, so
there's nothing to do).  It only fires on transitions from live to
expired.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from humanoid_robot.events import BaseEvent, SafetyWatchdogHeartbeat
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.safety.gate import SafetyGate

_LOG = get_logger("cortex-safety.watchdog")


@dataclass(slots=True)
class SafetyWatchdog:
    """Auto-engage e-stop when heartbeats stop arriving."""

    gate: SafetyGate
    bus: EventBusPort
    timeout_s: float = 5.0
    check_interval_s: float = 1.0
    actor: str = "watchdog"
    _last_heartbeat_at: float | None = None
    _was_live: bool = False
    _subscription: Subscription | None = None
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._subscription = await self.bus.subscribe(
            SafetyWatchdogHeartbeat.subject, self._on_heartbeat
        )
        self._task = asyncio.create_task(self._run(), name="safety-watchdog")

    async def stop(self) -> None:
        self._stop.set()
        if self._subscription is not None:
            try:
                await self._subscription.cancel()
            except Exception:
                _LOG.exception("watchdog.subscription_cancel_failed")
            self._subscription = None
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def is_live(self) -> bool:
        if self._last_heartbeat_at is None:
            return False
        return (time.monotonic() - self._last_heartbeat_at) <= self.timeout_s

    async def seconds_since_heartbeat(self) -> float | None:
        if self._last_heartbeat_at is None:
            return None
        return time.monotonic() - self._last_heartbeat_at

    async def _on_heartbeat(self, event: BaseEvent) -> None:
        if not isinstance(event, SafetyWatchdogHeartbeat):
            return
        self._last_heartbeat_at = time.monotonic()
        self._was_live = True

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                _LOG.exception("watchdog.tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.check_interval_s)
            except TimeoutError:
                continue

    async def _tick(self) -> None:
        if self._last_heartbeat_at is None:
            # No heartbeat yet — never entered live state, nothing to trip.
            return
        elapsed = time.monotonic() - self._last_heartbeat_at
        live = elapsed <= self.timeout_s
        if live:
            self._was_live = True
            return
        if not self._was_live:
            return
        # Live → expired transition.
        self._was_live = False
        engaged = await self.gate.engage_estop(
            actor=self.actor,
            reason=f"no heartbeat for {elapsed:.1f}s",
        )
        if engaged:
            _LOG.warning("watchdog.estop_engaged", elapsed=elapsed)
