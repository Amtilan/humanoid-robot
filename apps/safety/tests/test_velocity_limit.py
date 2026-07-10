"""VelocityLimitPolicy tests."""

from __future__ import annotations

import pytest

from humanoid_robot.ports import SafetyRequest
from humanoid_robot.safety import VelocityLimitPolicy


def _req(capability: str, payload: dict[str, object]) -> SafetyRequest:
    return SafetyRequest(command_id="cmd-1", capability=capability, payload=payload)


@pytest.mark.asyncio
async def test_within_envelope_allows() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=1.0, max_angular_rate_rps=1.0)
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 0.3, "linear_y_mps": 0.0, "angular_z_rps": 0.5},
        )
    )
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_over_linear_speed_denies() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=1.0, max_angular_rate_rps=1.0)
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 1.5, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    assert decision.verdict == "deny"
    assert "linear speed" in decision.reason


@pytest.mark.asyncio
async def test_diagonal_l2_norm_catches_over_limit() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=1.0, max_angular_rate_rps=1.0)
    # each axis 0.8 → hypot ≈ 1.13 > 1.0
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 0.8, "linear_y_mps": 0.8, "angular_z_rps": 0.0},
        )
    )
    assert decision.verdict == "deny"


@pytest.mark.asyncio
async def test_over_angular_denies() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=1.0, max_angular_rate_rps=1.0)
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 0.0, "linear_y_mps": 0.0, "angular_z_rps": 2.5},
        )
    )
    assert decision.verdict == "deny"
    assert "angular rate" in decision.reason


@pytest.mark.asyncio
async def test_other_capability_passes_through() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=0.1, max_angular_rate_rps=0.1)
    decision = await policy.evaluate(_req("arms.gesture", {"name": "wave"}))
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_non_numeric_payload_denies() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=1.0, max_angular_rate_rps=1.0)
    decision = await policy.evaluate(_req("locomotion.move", {"linear_x_mps": "fast"}))
    assert decision.verdict == "deny"
    assert "non-numeric" in decision.reason


@pytest.mark.asyncio
async def test_missing_fields_treated_as_zero() -> None:
    policy = VelocityLimitPolicy(max_linear_speed_mps=0.5, max_angular_rate_rps=0.5)
    decision = await policy.evaluate(_req("locomotion.move", {}))
    assert decision.verdict == "allow"
