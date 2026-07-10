"""SafetyGate — subscribes to robot.command.requested and applies policies."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    BaseEvent,
    RobotCommandRequested,
    SafetyCommandDenied,
    SafetyCommandForwarded,
    SafetyEStopEngaged,
    SafetyEStopReleased,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    EventBusPort,
    SafetyDecision,
    SafetyPolicyPort,
    SafetyRequest,
    Subscription,
)
from humanoid_robot.safety.estop import EStopState

_LOG = get_logger("cortex-safety.gate")


@dataclass(slots=True)
class SafetyGate:
    """Fail-closed gate — every motor command flows through here."""

    policy: SafetyPolicyPort
    bus: EventBusPort
    estop: EStopState
    producer: str = "cortex-safety"
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _subscription: Subscription | None = None
    _inflight: set[asyncio.Task[None]] = field(default_factory=set)

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._subscription = await self.bus.subscribe(
            RobotCommandRequested.subject, self._on_command
        )
        _LOG.info("safety_gate.ready")
        try:
            await self._stop.wait()
        finally:
            if self._subscription is not None:
                await self._subscription.cancel()
            for task in list(self._inflight):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._inflight.clear()

    async def _on_command(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotCommandRequested):
            return
        task = asyncio.create_task(self._handle(event), name=f"safety-eval[{event.command_id}]")
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle(self, event: RobotCommandRequested) -> None:
        request = SafetyRequest(
            command_id=event.command_id,
            capability=event.capability,
            payload=event.payload,
        )
        try:
            decision = await self.policy.evaluate(request)
        except Exception as exc:
            _LOG.exception("safety_gate.policy_failed", command_id=event.command_id)
            decision = SafetyDecision(
                verdict="deny",
                reason=f"policy_error: {type(exc).__name__}",
            )
        if decision.verdict == "allow":
            await self.bus.publish(
                SafetyCommandForwarded(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.producer,
                    ),
                    command_id=event.command_id,
                    capability=event.capability,
                    payload=event.payload,
                )
            )
            return
        await self.bus.publish(
            SafetyCommandDenied(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                command_id=event.command_id,
                capability=event.capability,
                reason=decision.reason,
            )
        )

    async def engage_estop(self, *, actor: str, reason: str | None = None) -> bool:
        changed = await self.estop.engage()
        if changed:
            await self.bus.publish(
                SafetyEStopEngaged(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.producer,
                    ),
                    actor=actor,
                    reason=reason,
                )
            )
        return changed

    async def release_estop(self, *, actor: str) -> bool:
        changed = await self.estop.release()
        if changed:
            await self.bus.publish(
                SafetyEStopReleased(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.producer,
                    ),
                    actor=actor,
                )
            )
        return changed
