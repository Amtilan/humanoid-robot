"""Safety events (e-stop lifecycle, command denials, forwarded commands)."""

from __future__ import annotations

from typing import Any, ClassVar

from humanoid_robot.events.base import BaseEvent


class SafetyEStopEngaged(BaseEvent):
    """Emergency stop was engaged; all motor commands must halt."""

    subject: ClassVar[str] = "safety.estop.engaged"
    schema_version: ClassVar[int] = 1

    actor: str
    reason: str | None = None


class SafetyEStopReleased(BaseEvent):
    """Emergency stop was released; commands may resume."""

    subject: ClassVar[str] = "safety.estop.released"
    schema_version: ClassVar[int] = 1

    actor: str


class SafetyCommandDenied(BaseEvent):
    """The safety gate rejected a command."""

    subject: ClassVar[str] = "safety.command.denied"
    schema_version: ClassVar[int] = 1

    command_id: str
    capability: str
    reason: str
    submitter: str = "unknown"


class SafetyCommandForwarded(BaseEvent):
    """The safety gate accepted a command and forwarded it to the adapter."""

    subject: ClassVar[str] = "safety.command.forwarded"
    schema_version: ClassVar[int] = 1

    command_id: str
    capability: str
    payload: dict[str, Any]
    submitter: str = "unknown"


class SafetyWatchdogHeartbeat(BaseEvent):
    """Operator liveness ping.

    The watchdog auto-engages the e-stop if no heartbeat arrives within
    a configured window.  Any actor (operator UI, deadman GPIO, remote
    console) may publish these.
    """

    subject: ClassVar[str] = "safety.watchdog.heartbeat"
    schema_version: ClassVar[int] = 1

    actor: str


class SafetyCommandTimeout(BaseEvent):
    """A forwarded command never received a `robot.command.result`.

    The reconciler emits this alongside auto-engaging the e-stop; the
    adapter may be hung, disconnected, or crashed.
    """

    subject: ClassVar[str] = "safety.command.timeout"
    schema_version: ClassVar[int] = 1

    command_id: str
    capability: str
    elapsed_s: float
