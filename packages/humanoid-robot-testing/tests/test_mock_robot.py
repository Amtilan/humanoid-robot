"""Tests for MockRobotAdapter."""

from __future__ import annotations

from humanoid_robot.domain.robot import MoveCommand, MoveOutcome, StopCommand
from humanoid_robot.testing import MockRobotAdapter


class TestMockRobotAdapter:
    async def test_starts_and_stops(self) -> None:
        adapter = MockRobotAdapter()
        assert not adapter.is_started
        await adapter.start()
        assert adapter.is_started
        # mypy 2.x narrows `is_started` too aggressively after the previous
        # assert and marks the next call as unreachable; suppress locally.
        await adapter.stop()  # type: ignore[unreachable]
        assert not adapter.is_started

    async def test_records_move_calls(self) -> None:
        adapter = MockRobotAdapter()
        cmd = MoveCommand(linear_x_mps=0.5, linear_y_mps=0.0, angular_z_rps=0.0)
        result = await adapter.locomotion.move(cmd)
        assert result.outcome == MoveOutcome.ACCEPTED
        assert adapter.moves == [cmd]

    async def test_records_stop_calls(self) -> None:
        adapter = MockRobotAdapter()
        cmd = StopCommand(reason="test")
        result = await adapter.locomotion.stop(cmd)
        assert result.outcome == MoveOutcome.ACCEPTED
        assert adapter.stops == [cmd]
