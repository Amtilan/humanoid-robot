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

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.adapters.unitree_g1.sdk import (
    SdkHandles,
    UnitreeSdkNotAvailableError,
    require_sdk,
)
from humanoid_robot.domain.robot import MoveOutcome, RobotCommandResult


@dataclass(slots=True)
class UnitreeG1Arm:
    """One arm, wired to a shared `G1ArmActionClient` instance.

    Off-robot the vendor SDK is unimportable, so ``_sdk`` may be ``None``
    at construction; it is resolved lazily by ``_ensure_client()``.
    """

    arm_id: str = "left"
    _sdk: SdkHandles | None = field(default=None)
    _client: Any = field(default=None)
    _initialised: bool = field(default=False)

    def attach_client(
        self,
        client: Any,
        *,
        action_map: dict[str, int] | None = None,
    ) -> None:
        """Test hook: supply a fake ArmClient with an action map."""
        module = _FakeArmModule(action_map=dict(action_map or {}), client=client)
        self._sdk = SdkHandles(channel=None, audio_client=None, arm_client=module)
        self._client = client
        self._initialised = True

    def _ensure_client(self) -> Any:
        if self._initialised:
            return self._client
        sdk = self._sdk
        if sdk is None:
            sdk = require_sdk()
            self._sdk = sdk
        self._client = sdk.arm_client.G1ArmActionClient()
        _try_call(self._client, "SetTimeout", 5.0)
        _try_call(self._client, "Init")
        self._initialised = True
        return self._client

    async def perform_gesture(self, gesture: str) -> RobotCommandResult:
        try:
            client = self._ensure_client()
        except UnitreeSdkNotAvailableError as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code="sdk_unavailable",
                error_message=str(exc)[:200],
            )
        sdk = self._sdk  # populated by _ensure_client above (else it raised)
        action_map: dict[str, int] = (
            getattr(sdk.arm_client, "action_map", {}) if sdk is not None else {}
        )
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
        try:
            # ExecuteAction blocks for the gesture's duration (seconds); run
            # it off the event loop so telemetry + other commands keep
            # flowing instead of stalling the whole adapter.
            rc = await asyncio.to_thread(client.ExecuteAction, action_id)
        except Exception as exc:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        if rc is not None and rc != 0:
            return RobotCommandResult(
                outcome=MoveOutcome.HARDWARE_ERROR,
                error_code=str(rc),
                error_message=f"ExecuteAction returned {rc}",
            )
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    async def release(self) -> RobotCommandResult:
        return await self.perform_gesture("release arm")

    def supported_gestures(self) -> tuple[str, ...]:
        if self._sdk is None:
            return ()
        return tuple(getattr(self._sdk.arm_client, "action_map", ()))


@dataclass(slots=True)
class _FakeArmModule:
    """Shim so `SdkHandles.arm_client.action_map` works without the vendor SDK."""

    action_map: dict[str, int]
    client: Any

    def G1ArmActionClient(self) -> Any:  # noqa: N802
        return self.client


def _try_call(client: Any, name: str, *args: object) -> None:
    fn = getattr(client, name, None)
    if callable(fn):
        with contextlib.suppress(Exception):
            fn(*args)
