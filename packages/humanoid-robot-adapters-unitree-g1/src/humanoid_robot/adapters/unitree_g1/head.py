"""HeadPort implementation over the Unitree G1 LocoClient.

The G1 head has 2 DOF (pitch + yaw) driven through the same LocoClient
that owns locomotion.  The SDK method name varies by firmware:
``SetHeadPose(pitch, yaw)`` on newer builds and ``HeadPose(pitch, yaw)``
on some, so we probe.

Off-robot the SDK is unimportable; everything happens through
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
    HeadPoseCommand,
    MoveOutcome,
    RobotCommandResult,
)

_LOG = logging.getLogger(__name__)


class UnitreeHeadUnavailableError(RuntimeError):
    """The installed SDK build doesn't ship head control."""

    def __init__(self) -> None:
        super().__init__(
            "unitree_sdk2py.g1.loco.g1_loco_client head-pose methods are not "
            "available; upgrade the vendor Python SDK or attach a fake client."
        )


@dataclass(slots=True)
class UnitreeG1Head:
    """HeadPort backed by the vendor LocoClient."""

    client: Any = None
    _initialised: bool = field(default=False)

    def _ensure_client(self) -> Any:  # noqa: ANN401 -- vendor LocoClient
        if self.client is not None:
            self._initialised = True
            return self.client
        handles: SdkHandles = require_sdk()
        loco_module = handles.loco_client
        if loco_module is None:
            raise UnitreeHeadUnavailableError
        cls = getattr(loco_module, "LocoClient", None)
        if cls is None:
            raise UnitreeHeadUnavailableError
        instance = cls()
        _try_call(instance, "Init")
        _try_call(instance, "SetTimeout", 1.0)
        self.client = instance
        self._initialised = True
        return instance

    async def set_pose(self, cmd: HeadPoseCommand) -> RobotCommandResult:
        try:
            client = self._ensure_client()
        except (UnitreeSdkNotAvailableError, UnitreeHeadUnavailableError) as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        try:
            code = _call_set_pose(client, pitch=cmd.pitch_rad, yaw=cmd.yaw_rad)
        except Exception as exc:
            _LOG.exception("unitree_g1.head.set_pose_failed")
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

    async def reset(self) -> RobotCommandResult:
        return await self.set_pose(HeadPoseCommand(pitch_rad=0.0, yaw_rad=0.0))


def _call_set_pose(client: Any, *, pitch: float, yaw: float) -> object:  # noqa: ANN401
    for name, args in (
        ("SetHeadPose", (pitch, yaw)),
        ("HeadPose", (pitch, yaw)),
        ("SetHead", (pitch, yaw)),
    ):
        fn = getattr(client, name, None)
        if callable(fn):
            return fn(*args)
    msg = "LocoClient has no head-pose method (SetHeadPose / HeadPose / SetHead)"
    raise AttributeError(msg)


def _try_call(client: Any, name: str, *args: object) -> None:  # noqa: ANN401
    fn = getattr(client, name, None)
    if callable(fn):
        try:
            fn(*args)
        except Exception:
            _LOG.exception("unitree_g1.head.%s_failed", name)


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
