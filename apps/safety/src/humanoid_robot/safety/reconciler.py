"""CommandReconciler — auto-engage e-stop when a forwarded command hangs.

Subscribes to ``safety.command.forwarded`` and ``robot.command.result``,
tracks pending commands with their monotonic start time, and every
``check_interval_s`` scans for commands older than ``timeout_s``.  On
expiry it emits ``safety.command.timeout`` and asks the gate to engage
the e-stop — better a stopped robot than one still moving to a
never-completing target.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    BaseEvent,
    RobotCommandResulted,
    SafetyCommandForwarded,
    SafetyCommandTimeout,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.safety.gate import SafetyGate

_LOG = get_logger("cortex-safety.reconciler")


@dataclass(slots=True)
class _Pending:
    capability: str
    started_at: float


@dataclass(slots=True)
class CommandReconciler:
    """Fires the e-stop when a forwarded command misses its deadline."""

    gate: SafetyGate
    bus: EventBusPort
    timeout_s: float = 3.0
    check_interval_s: float = 0.5
    actor: str = "reconciler"
    _pending: dict[str, _Pending] = field(default_factory=dict)
    _forwarded_sub: Subscription | None = None
    _result_sub: Subscription | None = None
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._forwarded_sub = await self.bus.subscribe(
            SafetyCommandForwarded.subject, self._on_forwarded
        )
        self._result_sub = await self.bus.subscribe(RobotCommandResulted.subject, self._on_result)
        self._task = asyncio.create_task(self._run(), name="safety-reconciler")

    async def stop(self) -> None:
        self._stop.set()
        for sub in (self._forwarded_sub, self._result_sub):
            if sub is None:
                continue
            with contextlib.suppress(Exception):
                await sub.cancel()
        self._forwarded_sub = None
        self._result_sub = None
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def pending_count(self) -> int:
        return len(self._pending)

    def pending_ids(self) -> tuple[str, ...]:
        return tuple(self._pending.keys())

    async def _on_forwarded(self, event: BaseEvent) -> None:
        if not isinstance(event, SafetyCommandForwarded):
            return
        self._pending[event.command_id] = _Pending(
            capability=event.capability, started_at=time.monotonic()
        )

    async def _on_result(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotCommandResulted):
            return
        self._pending.pop(event.command_id, None)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                _LOG.exception("reconciler.tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.check_interval_s)
            except TimeoutError:
                continue

    async def _tick(self) -> None:
        if not self._pending:
            return
        now = time.monotonic()
        expired = [
            (command_id, pending)
            for command_id, pending in self._pending.items()
            if now - pending.started_at > self.timeout_s
        ]
        if not expired:
            return
        for command_id, pending in expired:
            self._pending.pop(command_id, None)
            elapsed = now - pending.started_at
            await self.bus.publish(
                SafetyCommandTimeout(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer="cortex-safety",
                    ),
                    command_id=command_id,
                    capability=pending.capability,
                    elapsed_s=elapsed,
                )
            )
            _LOG.warning(
                "reconciler.command_timeout",
                command_id=command_id,
                capability=pending.capability,
                elapsed=elapsed,
            )
        await self.gate.engage_estop(
            actor=self.actor,
            reason=f"command timeout ({len(expired)} pending > {self.timeout_s:.1f}s)",
        )
