"""PosturePort implementation over the Unitree G1 LocoClient.

Maps domain PostureKind values to the vendor LocoClient mode calls
(``Damp`` / ``StandUp`` / ``BalanceStand`` / …). These are the whole-body
FSM transitions that were previously only reachable by direct SDK calls
bypassing the safety gate; routing them through a port means they now go
through the gate (estop, rate-limit, audit) like every other command.

Off-robot the SDK is unimportable; the client is resolved lazily via
``require_sdk()`` on the first call.
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
    MoveOutcome,
    PostureCommand,
    PostureKind,
    RobotCommandResult,
)

_LOG = logging.getLogger(__name__)

# balance_mode passed to LocoClient.BalanceStand / SetBalanceMode. 0 is the
# static stand-balance mode (vs a continuous-gait mode); safe default.
_BALANCE_MODE_STATIC = 0

# PostureKind -> ordered candidate (method_name, args) tuples. We probe in
# order and use the first method the installed SDK actually exposes,
# because the Python and C++ SDKs disagree on names: the Python
# unitree_sdk2py LocoClient has `Squat2StandUp` / `StandUp2Squat` /
# `Lie2StandUp` (no bare `StandUp` / `Squat`), and `BalanceStand` REQUIRES
# a balance_mode argument. dir() on the installed client confirmed:
# Damp, ZeroTorque, Sit, Squat2StandUp, StandUp2Squat, Lie2StandUp,
# BalanceStand, HighStand, LowStand, StopMove.
_Call = tuple[str, tuple[object, ...]]
_CANDIDATES_BY_POSTURE: dict[PostureKind, tuple[_Call, ...]] = {
    PostureKind.DAMP: (("Damp", ()),),
    PostureKind.ZERO_TORQUE: (("ZeroTorque", ()),),
    PostureKind.SIT: (("Sit", ()),),
    PostureKind.SQUAT: (("Squat", ()), ("StandUp2Squat", ())),
    PostureKind.STAND_UP: (("StandUp", ()), ("Squat2StandUp", ()), ("Lie2StandUp", ())),
    PostureKind.BALANCE_STAND: (("BalanceStand", (_BALANCE_MODE_STATIC,)),),
    PostureKind.HIGH_STAND: (("HighStand", ()),),
    PostureKind.LOW_STAND: (("LowStand", ()),),
    PostureKind.STOP_MOVE: (("StopMove", ()),),
}


class UnitreePostureUnavailableError(RuntimeError):
    """The installed SDK build doesn't ship the LocoClient."""

    def __init__(self) -> None:
        super().__init__(
            "unitree_sdk2py.g1.loco.g1_loco_client.LocoClient is not available "
            "in this SDK build; upgrade the vendor Python SDK or attach a fake."
        )


@dataclass(slots=True)
class UnitreeG1Posture:
    """PosturePort backed by the vendor LocoClient."""

    client: Any = None
    _initialised: bool = field(default=False)

    def _ensure_client(self) -> Any:  # noqa: ANN401 -- vendor LocoClient is untyped
        if self.client is not None:
            self._initialised = True
            return self.client
        handles: SdkHandles = require_sdk()
        loco_module = handles.loco_client
        if loco_module is None:
            raise UnitreePostureUnavailableError
        cls = getattr(loco_module, "LocoClient", None)
        if cls is None:
            raise UnitreePostureUnavailableError
        instance = cls()
        _try_call(instance, "SetTimeout", 3.0)
        _try_call(instance, "Init")
        self.client = instance
        self._initialised = True
        return instance

    async def set_posture(self, cmd: PostureCommand) -> RobotCommandResult:
        candidates = _CANDIDATES_BY_POSTURE.get(cmd.posture)
        if not candidates:  # pragma: no cover - enum keeps this exhaustive
            return RobotCommandResult(
                outcome=MoveOutcome.REJECTED_BY_POLICY,
                error_code="unknown_posture",
                error_message=f"no LocoClient mapping for posture {cmd.posture!r}",
            )
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreePostureUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        method, args = _first_available(client, candidates)
        if method is None:
            names = ", ".join(name for name, _ in candidates)
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="method_missing",
                error_message=f"LocoClient has none of: {names}",
            )
        try:
            code = getattr(client, method)(*args)
        except Exception as exc:
            _LOG.exception("unitree_g1.posture.%s_failed", method)
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
            error_message=f"{method}() returned {code!r}",
        )


def _first_available(
    client: Any,  # noqa: ANN401
    candidates: tuple[_Call, ...],
) -> tuple[str | None, tuple[object, ...]]:
    """First (name, args) whose method the client actually exposes."""
    for name, args in candidates:
        if callable(getattr(client, name, None)):
            return name, args
    return None, ()


def _try_call(client: Any, name: str, *args: object) -> None:  # noqa: ANN401
    fn = getattr(client, name, None)
    if callable(fn):
        try:
            fn(*args)
        except Exception:
            _LOG.exception("unitree_g1.posture.%s_failed", name)


def _is_ok_code(code: object) -> bool:
    # LocoClient calls return None on success on this SDK build; 0 / "" /
    # "ok" are the other success conventions seen across versions.
    if code is None:
        return True
    if isinstance(code, bool):
        return code
    if isinstance(code, (int, float)):
        return int(code) == 0
    if isinstance(code, str):
        return code.lower() in {"", "ok", "success"}
    return True
