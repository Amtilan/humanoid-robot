"""HandPort implementation for the Unitree G1 dexterous hands.

The G1 ships with several optional hand modules (``dex3``, ``inspire``,
``linker_o6``, ``brainco``) or none.  Each vendor exposes its own
client, so this adapter takes a ``hand_kind`` string and probes the
underlying SDK for the matching client.  If the configured kind is
``none`` — the platform's fail-closed default — every operation
returns ``REJECTED_BY_POLICY / no_hand_configured``.

Same shape as the arm/head adapters: pluggable ``client`` for tests,
``attach_client`` hook for injection, all vendor errors collapsed into
typed RobotCommandResults.
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
from humanoid_robot.domain.robot import MoveOutcome, RobotCommandResult

_LOG = logging.getLogger(__name__)


class UnitreeHandUnavailableError(RuntimeError):
    """The installed SDK build doesn't ship the requested hand client."""

    def __init__(self, kind: str) -> None:
        super().__init__(
            f"unitree_sdk2py hand client for kind {kind!r} is not available; "
            "install the vendor package for that hand module or attach a fake."
        )


@dataclass(slots=True)
class UnitreeG1Hand:
    """HandPort backed by whichever hand client the G1 has attached."""

    hand_kind: str = "none"
    client: Any = None
    _sdk: SdkHandles | None = field(default=None)
    _initialised: bool = field(default=False)

    def attach_client(self, client: Any) -> None:  # noqa: ANN401
        """Test hook: inject any object satisfying the vendor hand API."""
        self.client = client
        self._initialised = True

    def _ensure_client(self) -> Any:  # noqa: ANN401
        if self._initialised or self.client is not None:
            self._initialised = True
            return self.client
        if self.hand_kind == "none":
            return None
        sdk = self._sdk
        if sdk is None:
            sdk = require_sdk()
            self._sdk = sdk
        # Vendor packaging varies; probe common attribute names on the
        # audio_client umbrella (some builds group hand clients there).
        for holder_attr in ("hand_client", "hands_client", "audio_client"):
            holder = getattr(sdk, holder_attr, None)
            if holder is None:
                continue
            for cls_name in ("Dex3Client", "InspireClient", "LinkerO6Client", "BrainCoClient"):
                cls = getattr(holder, cls_name, None)
                if callable(cls):
                    instance = cls()
                    _try_call(instance, "Init")
                    _try_call(instance, "SetTimeout", 1.0)
                    self.client = instance
                    self._initialised = True
                    return instance
        raise UnitreeHandUnavailableError(self.hand_kind)

    async def open(self) -> RobotCommandResult:
        return await self._call_named("Open", "open")

    async def close(self) -> RobotCommandResult:
        return await self._call_named("Close", "close")

    async def set_positions(self, positions: tuple[float, ...]) -> RobotCommandResult:
        if not positions:
            return RobotCommandResult(
                outcome=MoveOutcome.REJECTED_BY_POLICY,
                error_code="empty_positions",
                error_message="set_positions requires at least one joint value",
            )
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreeHandUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        if client is None:
            return _no_hand()
        try:
            code = _call_set_positions(client, positions)
        except Exception as exc:
            _LOG.exception("unitree_g1.hand.set_positions_failed")
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        return _result_from_code(code)

    async def _call_named(self, method_name: str, op: str) -> RobotCommandResult:
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreeHandUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        if client is None:
            return _no_hand()
        fn = getattr(client, method_name, None)
        if not callable(fn):
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="AttributeError",
                error_message=f"hand client has no {method_name} method",
            )
        try:
            code = fn()
        except Exception as exc:
            _LOG.exception("unitree_g1.hand.%s_failed", op)
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        return _result_from_code(code)


def _call_set_positions(client: Any, positions: tuple[float, ...]) -> object:  # noqa: ANN401
    for name in ("SetPositions", "SetPose", "SetJointPositions"):
        fn = getattr(client, name, None)
        if callable(fn):
            return fn(list(positions))
    msg = "hand client has no SetPositions / SetPose / SetJointPositions"
    raise AttributeError(msg)


def _try_call(client: Any, name: str, *args: object) -> None:  # noqa: ANN401
    fn = getattr(client, name, None)
    if callable(fn):
        try:
            fn(*args)
        except Exception:
            _LOG.exception("unitree_g1.hand.%s_failed", name)


def _no_hand() -> RobotCommandResult:
    return RobotCommandResult(
        outcome=MoveOutcome.REJECTED_BY_POLICY,
        error_code="no_hand_configured",
        error_message="adapter was booted with hand_kind='none'",
    )


def _result_from_code(code: object) -> RobotCommandResult:
    if code is None or (isinstance(code, (int, float)) and int(code) == 0):
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)
    if isinstance(code, bool):
        return (
            RobotCommandResult(outcome=MoveOutcome.ACCEPTED)
            if code
            else RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="hand_client_error",
                error_message="hand client returned False",
            )
        )
    return RobotCommandResult(
        outcome=MoveOutcome.HARDWARE_ERROR,
        error_code="hand_client_error",
        error_message=f"hand client returned {code!r}",
    )
