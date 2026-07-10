"""UnitreeG1Posture tests with an injected fake LocoClient."""

from __future__ import annotations

from dataclasses import dataclass, field

from humanoid_robot.adapters.unitree_g1.adapter import UnitreeG1Adapter
from humanoid_robot.adapters.unitree_g1.posture import UnitreeG1Posture
from humanoid_robot.domain.robot import MoveOutcome, PostureCommand, PostureKind


@dataclass(slots=True)
class _FakeLocoClient:
    calls: list[str] = field(default_factory=list)
    ret: object = None
    raises: BaseException | None = None

    def Init(self) -> None:  # noqa: N802
        return None

    def SetTimeout(self, _s: float) -> None:  # noqa: N802
        return None

    def _record(self, name: str) -> object:
        if self.raises is not None:
            raise self.raises
        self.calls.append(name)
        return self.ret

    def Damp(self) -> object:  # noqa: N802
        return self._record("Damp")

    def BalanceStand(self) -> object:  # noqa: N802
        return self._record("BalanceStand")

    def StandUp(self) -> object:  # noqa: N802
        return self._record("StandUp")

    def ZeroTorque(self) -> object:  # noqa: N802
        return self._record("ZeroTorque")


class TestPosture:
    async def test_damp_calls_loco_damp(self) -> None:
        client = _FakeLocoClient()
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.DAMP))
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.calls == ["Damp"]

    async def test_balance_stand_maps_to_balance_stand(self) -> None:
        client = _FakeLocoClient()
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.BALANCE_STAND))
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.calls == ["BalanceStand"]

    async def test_none_return_is_accepted(self) -> None:
        # LocoClient returns None on success on the real SDK build.
        client = _FakeLocoClient(ret=None)
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.STAND_UP))
        assert result.outcome == MoveOutcome.ACCEPTED

    async def test_non_zero_return_is_hardware_error(self) -> None:
        client = _FakeLocoClient(ret=7404)
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.BALANCE_STAND))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "loco_client_error"
        assert "7404" in (result.error_message or "")

    async def test_exception_is_typed_hardware_error(self) -> None:
        client = _FakeLocoClient(raises=RuntimeError("fsm rejected"))
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.DAMP))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "RuntimeError"
        assert "fsm rejected" in (result.error_message or "")

    async def test_method_missing_is_hardware_error(self) -> None:
        # A LocoClient that lacks the requested method (e.g. HighStand).
        client = _FakeLocoClient()
        posture = UnitreeG1Posture(client=client)
        result = await posture.set_posture(PostureCommand(posture=PostureKind.HIGH_STAND))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "method_missing"

    async def test_missing_sdk_reports_sdk_unavailable(self) -> None:
        posture = UnitreeG1Posture()
        result = await posture.set_posture(PostureCommand(posture=PostureKind.DAMP))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "sdk_unavailable"


class TestAdapterIntegration:
    async def test_attach_posture_client_lets_adapter_transition(self) -> None:
        client = _FakeLocoClient()
        adapter = UnitreeG1Adapter()
        adapter.attach_posture_client(client)
        result = await adapter.posture.set_posture(PostureCommand(posture=PostureKind.BALANCE_STAND))
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.calls == ["BalanceStand"]
