"""UnitreeG1LocomotionAdapter tests using an injected fake LocoClient."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.unitree_g1.adapter import UnitreeG1Adapter
from humanoid_robot.adapters.unitree_g1.locomotion import (
    UnitreeG1LocomotionAdapter,
    UnitreeLocomotionUnavailableError,
)
from humanoid_robot.domain.robot import MoveCommand, MoveOutcome, StopCommand


@dataclass(slots=True)
class _FakeLocoClient:
    """Records the exact arguments the adapter forwards to the SDK."""

    move_calls: list[tuple[float, float, float, float]] = field(default_factory=list)
    stop_calls: int = 0
    move_return: int = 0
    stop_return: int = 0
    move_raises: BaseException | None = None

    # SDK entry points
    def Init(self) -> None:  # noqa: N802 -- vendor SDK naming
        return None

    def SetTimeout(self, _seconds: float) -> None:  # noqa: N802
        return None

    def Move(self, vx: float, vy: float, omega: float, duration: float) -> int:  # noqa: N802
        if self.move_raises is not None:
            raise self.move_raises
        self.move_calls.append((vx, vy, omega, duration))
        return self.move_return

    def StopMove(self) -> int:  # noqa: N802
        self.stop_calls += 1
        return self.stop_return


class TestLocomotion:
    async def test_move_forwards_velocity_and_returns_accepted(self) -> None:
        client = _FakeLocoClient()
        loco = UnitreeG1LocomotionAdapter(client=client)
        result = await loco.move(
            MoveCommand(linear_x_mps=0.3, linear_y_mps=0.0, angular_z_rps=0.5, duration_ms=500)
        )
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.move_calls == [(0.3, 0.0, 0.5, 0.5)]

    async def test_move_wraps_hardware_error(self) -> None:
        client = _FakeLocoClient(move_raises=RuntimeError("dds timeout"))
        loco = UnitreeG1LocomotionAdapter(client=client)
        result = await loco.move(MoveCommand(linear_x_mps=0.1, linear_y_mps=0.0, angular_z_rps=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "RuntimeError"
        assert "dds timeout" in (result.error_message or "")

    async def test_non_zero_return_code_maps_to_hardware_error(self) -> None:
        client = _FakeLocoClient(move_return=7)
        loco = UnitreeG1LocomotionAdapter(client=client)
        result = await loco.move(MoveCommand(linear_x_mps=0.1, linear_y_mps=0.0, angular_z_rps=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "loco_client_error"

    async def test_stop_calls_stopmove(self) -> None:
        client = _FakeLocoClient()
        loco = UnitreeG1LocomotionAdapter(client=client)
        result = await loco.stop(StopCommand())
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.stop_calls == 1

    async def test_missing_sdk_reports_sdk_unavailable(self) -> None:
        # No client provided, and require_sdk() must fail because the vendor
        # package isn't installed in the test environment.
        loco = UnitreeG1LocomotionAdapter()
        result = await loco.move(MoveCommand(linear_x_mps=0.0, linear_y_mps=0.0, angular_z_rps=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "sdk_unavailable"


class TestAdapterIntegration:
    async def test_attach_locomotion_client_lets_adapter_move(self) -> None:
        client = _FakeLocoClient()
        adapter = UnitreeG1Adapter()
        adapter.attach_locomotion_client(client)

        result = await adapter.move(
            MoveCommand(linear_x_mps=0.4, linear_y_mps=0.0, angular_z_rps=0.0, duration_ms=200)
        )
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.move_calls == [(0.4, 0.0, 0.0, 0.2)]

    async def test_stop_locomotion_routes_to_client(self) -> None:
        client = _FakeLocoClient()
        adapter = UnitreeG1Adapter()
        adapter.attach_locomotion_client(client)

        result = await adapter.stop_locomotion(StopCommand())
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.stop_calls == 1


class TestUnavailability:
    def test_loco_unavailable_exception_message_mentions_sdk(self) -> None:
        with pytest.raises(UnitreeLocomotionUnavailableError, match="loco_client"):
            raise UnitreeLocomotionUnavailableError
