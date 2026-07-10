"""UnitreeG1Hand tests with an injected fake client."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.unitree_g1.adapter import UnitreeG1Adapter
from humanoid_robot.adapters.unitree_g1.hand import (
    UnitreeG1Hand,
    UnitreeHandUnavailableError,
)
from humanoid_robot.domain.robot import MoveOutcome


@dataclass(slots=True)
class _FakeHand:
    opens: int = 0
    closes: int = 0
    positions: list[list[float]] = field(default_factory=list)
    open_return: int = 0
    close_return: int = 0
    positions_return: int = 0
    open_raises: BaseException | None = None

    def Init(self) -> None:  # noqa: N802
        return None

    def SetTimeout(self, _s: float) -> None:  # noqa: N802
        return None

    def Open(self) -> int:  # noqa: N802
        if self.open_raises is not None:
            raise self.open_raises
        self.opens += 1
        return self.open_return

    def Close(self) -> int:  # noqa: N802
        self.closes += 1
        return self.close_return

    def SetPositions(self, positions: list[float]) -> int:  # noqa: N802
        self.positions.append(list(positions))
        return self.positions_return


class TestHand:
    async def test_open_and_close_flow(self) -> None:
        client = _FakeHand()
        hand = UnitreeG1Hand(hand_kind="dex3", client=client)
        assert (await hand.open()).outcome == MoveOutcome.ACCEPTED
        assert (await hand.close()).outcome == MoveOutcome.ACCEPTED
        assert client.opens == 1
        assert client.closes == 1

    async def test_set_positions_forwards_list(self) -> None:
        client = _FakeHand()
        hand = UnitreeG1Hand(hand_kind="dex3", client=client)
        result = await hand.set_positions((0.1, 0.5, 0.9))
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.positions == [[0.1, 0.5, 0.9]]

    async def test_empty_positions_rejected_before_touching_client(self) -> None:
        client = _FakeHand()
        hand = UnitreeG1Hand(hand_kind="dex3", client=client)
        result = await hand.set_positions(())
        assert result.outcome == MoveOutcome.REJECTED_BY_POLICY
        assert result.error_code == "empty_positions"
        assert client.positions == []

    async def test_exception_becomes_hardware_error(self) -> None:
        client = _FakeHand(open_raises=RuntimeError("slippage"))
        hand = UnitreeG1Hand(hand_kind="dex3", client=client)
        result = await hand.open()
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "RuntimeError"
        assert "slippage" in (result.error_message or "")

    async def test_non_zero_code_is_hardware_error(self) -> None:
        client = _FakeHand(open_return=5)
        hand = UnitreeG1Hand(hand_kind="dex3", client=client)
        result = await hand.open()
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "hand_client_error"

    async def test_none_kind_reports_no_hand_configured(self) -> None:
        hand = UnitreeG1Hand(hand_kind="none")
        result = await hand.open()
        assert result.outcome == MoveOutcome.REJECTED_BY_POLICY
        assert result.error_code == "no_hand_configured"

    async def test_missing_sdk_reports_sdk_unavailable(self) -> None:
        # dex3 kind but no client → require_sdk() runs and fails off-robot.
        hand = UnitreeG1Hand(hand_kind="dex3")
        result = await hand.open()
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "sdk_unavailable"


class TestAdapterIntegration:
    async def test_attach_hand_client_lets_adapter_operate(self) -> None:
        client = _FakeHand()
        adapter = UnitreeG1Adapter()
        adapter.attach_hand_client(client, hand_kind="dex3")
        result = await adapter.hand.close()
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.closes == 1


class TestUnavailable:
    def test_error_message_mentions_kind(self) -> None:
        with pytest.raises(UnitreeHandUnavailableError, match="dex3"):
            raise UnitreeHandUnavailableError("dex3")
