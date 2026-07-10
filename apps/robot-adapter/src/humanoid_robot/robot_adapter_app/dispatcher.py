"""CommandDispatcher — the *only* place motor commands leave the platform.

Subscribes to ``safety.command.forwarded`` (never ``robot.command.requested``
— those must always transit the safety gate first) and routes each command
to a registered capability handler.  Every dispatch publishes a
``robot.command.result`` so orchestrators can wait on it.

Unhandled capabilities produce a ``robot.command.result`` with a
``rejected_by_policy`` outcome — this stays consistent with the fail-closed
contract of the safety layer.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from humanoid_robot.domain.robot import (
    HeadPoseCommand,
    MoveCommand,
    MoveOutcome,
    RobotCommandResult,
    StopCommand,
)
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    BaseEvent,
    RobotCommandResulted,
    SafetyCommandForwarded,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    ArmPort,
    EventBusPort,
    HeadPort,
    LocomotionPort,
    Subscription,
)

_LOG = get_logger("cortex-robot-adapter.dispatcher")

CommandHandler = Callable[[dict[str, object]], Awaitable[RobotCommandResult]]


@dataclass(slots=True)
class CommandDispatcher:
    """Routes forwarded safety-gate commands to per-capability handlers."""

    bus: EventBusPort
    handlers: dict[str, CommandHandler] = field(default_factory=dict)
    producer: str = "cortex-robot-adapter"
    _subscription: Subscription | None = None
    _inflight: set[asyncio.Task[None]] = field(default_factory=set)

    def register(self, capability: str, handler: CommandHandler) -> None:
        self.handlers[capability] = handler

    def register_locomotion(self, locomotion: LocomotionPort) -> None:
        async def _move(payload: dict[str, object]) -> RobotCommandResult:
            return await locomotion.move(MoveCommand.model_validate(payload))

        async def _stop(payload: dict[str, object]) -> RobotCommandResult:
            return await locomotion.stop(StopCommand.model_validate(payload))

        self.register("locomotion.move", _move)
        self.register("locomotion.stop", _stop)

    def register_arm(self, arm: ArmPort) -> None:
        async def _gesture(payload: dict[str, object]) -> RobotCommandResult:
            name = payload.get("gesture")
            if not isinstance(name, str) or not name:
                return RobotCommandResult(
                    outcome=MoveOutcome.REJECTED_BY_POLICY,
                    error_code="missing_gesture",
                    error_message="payload must include 'gesture': str",
                )
            return await arm.perform_gesture(name)

        async def _release(_payload: dict[str, object]) -> RobotCommandResult:
            return await arm.release()

        self.register("arms.gesture", _gesture)
        self.register("arms.release", _release)

    def register_head(self, head: HeadPort) -> None:
        async def _pose(payload: dict[str, object]) -> RobotCommandResult:
            return await head.set_pose(HeadPoseCommand.model_validate(payload))

        async def _reset(_payload: dict[str, object]) -> RobotCommandResult:
            return await head.reset()

        self.register("head.pose", _pose)
        self.register("head.reset", _reset)

    async def start(self) -> None:
        if self._subscription is not None:
            return
        self._subscription = await self.bus.subscribe(
            SafetyCommandForwarded.subject, self._on_forwarded
        )
        _LOG.info(
            "command_dispatcher.ready",
            capabilities=sorted(self.handlers.keys()),
        )

    async def stop(self) -> None:
        if self._subscription is not None:
            with contextlib.suppress(Exception):
                await self._subscription.cancel()
            self._subscription = None
        for task in list(self._inflight):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._inflight.clear()

    async def _on_forwarded(self, event: BaseEvent) -> None:
        if not isinstance(event, SafetyCommandForwarded):
            return
        task = asyncio.create_task(self._handle(event), name=f"dispatch[{event.command_id}]")
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle(self, event: SafetyCommandForwarded) -> None:
        handler = self.handlers.get(event.capability)
        if handler is None:
            result = RobotCommandResult(
                outcome=MoveOutcome.REJECTED_BY_POLICY,
                error_code="capability_unsupported",
                error_message=f"no handler for {event.capability!r}",
            )
        else:
            try:
                result = await handler(event.payload)
            except Exception as exc:
                _LOG.exception(
                    "command_dispatcher.handler_failed",
                    command_id=event.command_id,
                    capability=event.capability,
                )
                result = RobotCommandResult(
                    outcome=MoveOutcome.HARDWARE_ERROR,
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:200],
                )

        await self.bus.publish(
            RobotCommandResulted(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                command_id=event.command_id,
                result=result,
            )
        )
