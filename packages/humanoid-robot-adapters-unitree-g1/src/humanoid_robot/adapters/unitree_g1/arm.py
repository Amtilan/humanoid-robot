"""G1 arm — `ArmPort` implementation on top of `G1ArmActionClient`.

Design:
    - One instance per physical arm ("left" or "right").
    - `perform_gesture(name)` looks the name up in the SDK's `action_map`.
      Unknown gestures return `MoveOutcome.REJECTED_BY_POLICY` so the caller
      can act on it without an exception.
    - `supported_gestures()` reads the SDK-provided `action_map` at import
      time (via the injected `SdkHandles`), so `manifest` and the runtime
      view stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.adapters.unitree_g1.sdk import SdkHandles
from humanoid_robot.domain.robot import MoveOutcome, RobotCommandResult


@dataclass(slots=True)
class UnitreeG1Arm:
    """One arm, wired to a shared `G1ArmActionClient` instance."""

    arm_id: str
    _sdk: SdkHandles
    _client: Any = field(default=None, init=False)
    _initialised: bool = field(default=False, init=False)

    def _ensure_client(self) -> Any:
        if not self._initialised:
            self._client = self._sdk.arm_client.G1ArmActionClient()
            self._client.SetTimeout(5.0)
            self._client.Init()
            self._initialised = True
        return self._client

    async def perform_gesture(self, gesture: str) -> RobotCommandResult:
        action_map: dict[str, int] = self._sdk.arm_client.action_map
        action_id = action_map.get(gesture)
        if action_id is None:
            return RobotCommandResult(
                outcome=MoveOutcome.REJECTED_BY_POLICY,
                error_code="UNKNOWN_GESTURE",
                error_message=(
                    f"gesture {gesture!r} is not in the SDK action_map; "
                    f"available: {sorted(action_map)}"
                ),
            )
        client = self._ensure_client()
        rc = client.ExecuteAction(action_id)
        if rc != 0:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=str(rc),
                error_message=f"ExecuteAction returned {rc}",
            )
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    async def release(self) -> RobotCommandResult:
        return await self.perform_gesture("release arm")

    def supported_gestures(self) -> tuple[str, ...]:
        return tuple(self._sdk.arm_client.action_map)
