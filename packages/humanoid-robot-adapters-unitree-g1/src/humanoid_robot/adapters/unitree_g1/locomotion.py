"""LocomotionPort implementation over the Unitree G1 LocoClient.

Wraps `unitree_sdk2py.g1.loco.g1_loco_client.LocoClient`.  The concrete
method name varies by SDK version (``Move`` on newer builds,
``SetVelocity`` on older ones); we probe both and prefer whichever the
installed vendor package exposes.

Off-robot the SDK is unimportable, so this module builds no client at
import time — everything happens through ``require_sdk()`` on the first
call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.adapters.unitree_g1.sdk import (
    SdkHandles,
    UnitreeSdkNotAvailableError,
    require_sdk,
)
from humanoid_robot.domain.robot import (
    MoveCommand,
    MoveOutcome,
    RobotCommandResult,
    StopCommand,
)

_LOG = logging.getLogger(__name__)


class UnitreeLocomotionUnavailableError(RuntimeError):
    """The installed SDK build doesn't ship G1 LocoClient."""

    def __init__(self) -> None:
        super().__init__(
            "unitree_sdk2py.g1.loco.g1_loco_client is not available in this SDK build; "
            "upgrade the vendor Python SDK or attach a fake client for tests."
        )


@dataclass(slots=True)
class UnitreeG1LocomotionAdapter:
    """LocomotionPort backed by the vendor LocoClient.

    ``client`` is passed in for tests; when omitted the adapter lazily
    creates one from ``require_sdk()``.
    """

    client: Any = None
    _initialised: bool = field(default=False)

    def _ensure_client(self) -> Any:  # noqa: ANN401 -- vendor LocoClient is untyped
        if self.client is not None:
            self._initialised = True
            return self.client
        handles: SdkHandles = require_sdk()
        loco_module = handles.loco_client
        if loco_module is None:
            raise UnitreeLocomotionUnavailableError
        cls = getattr(loco_module, "LocoClient", None)
        if cls is None:
            raise UnitreeLocomotionUnavailableError
        instance = cls()
        _try_call(instance, "Init")
        _try_call(instance, "SetTimeout", 1.0)
        self.client = instance
        self._initialised = True
        return instance

    async def move(self, cmd: MoveCommand) -> RobotCommandResult:
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreeLocomotionUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        try:
            duration_s = max(cmd.duration_ms / 1000.0, 0.0)
            code = _call_move(
                client,
                vx=cmd.linear_x_mps,
                vy=cmd.linear_y_mps,
                omega=cmd.angular_z_rps,
                duration_s=duration_s,
            )
        except Exception as exc:
            _LOG.exception("unitree_g1.locomotion.move_failed")
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        if _is_ok_code(code):
            return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)
        return RobotCommandResult(
            outcome=MoveOutcome.HARDWARE_ERROR,
            error_code="loco_client_error",
            error_message=f"LocoClient returned {code!r}",
        )

    async def stop(self, cmd: StopCommand) -> RobotCommandResult:
        del cmd  # reason lives on the calling event; nothing to relay downstream
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreeLocomotionUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        try:
            code = _call_stop(client)
        except Exception as exc:
            _LOG.exception("unitree_g1.locomotion.stop_failed")
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        if _is_ok_code(code):
            return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)
        return RobotCommandResult(
            outcome=MoveOutcome.HARDWARE_ERROR,
            error_code="loco_client_error",
            error_message=f"LocoClient returned {code!r}",
        )


def _call_move(
    client: Any,  # noqa: ANN401 -- vendor LocoClient
    *,
    vx: float,
    vy: float,
    omega: float,
    duration_s: float,
) -> object:
    """Route to whichever move method the installed SDK exposes."""
    for name, args in (
        ("Move", (vx, vy, omega, duration_s)),
        ("SetVelocity", (vx, vy, omega, duration_s)),
    ):
        fn = getattr(client, name, None)
        if callable(fn):
            return fn(*args)
    msg = "LocoClient has neither Move nor SetVelocity method"
    raise AttributeError(msg)


def _call_stop(client: Any) -> object:  # noqa: ANN401
    for name in ("StopMove", "Damp", "Stop"):
        fn = getattr(client, name, None)
        if callable(fn):
            return fn()
    msg = "LocoClient has no stop-like method"
    raise AttributeError(msg)


def _try_call(client: Any, name: str, *args: object) -> None:  # noqa: ANN401
    fn = getattr(client, name, None)
    if callable(fn):
        try:
            fn(*args)
        except Exception:
            _LOG.exception("unitree_g1.locomotion.%s_failed", name)


def _is_ok_code(code: object) -> bool:
    if code is None:
        return True
    if isinstance(code, bool):
        return code
    if isinstance(code, (int, float)):
        return int(code) == 0
    if isinstance(code, str):
        return code.lower() in {"", "ok", "success"}
    return True
