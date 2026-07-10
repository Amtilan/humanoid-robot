"""PayloadSchemaPolicy tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from humanoid_robot.ports import SafetyRequest
from humanoid_robot.safety import PayloadSchemaPolicy


def _req(capability: str, payload: dict[str, object]) -> SafetyRequest:
    return SafetyRequest(command_id="cmd-1", capability=capability, payload=payload)


@pytest.mark.asyncio
async def test_valid_move_payload_allows() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 0.3, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_invalid_move_payload_denies_with_field() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(_req("locomotion.move", {"linear_x_mps": "fast"}))
    assert decision.verdict == "deny"
    assert "linear_x_mps" in decision.reason


@pytest.mark.asyncio
async def test_out_of_range_denies() -> None:
    policy = PayloadSchemaPolicy()
    # MoveCommand caps linear at ±5.0 m/s
    decision = await policy.evaluate(
        _req(
            "locomotion.move",
            {"linear_x_mps": 99.0, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    assert decision.verdict == "deny"
    assert "linear_x_mps" in decision.reason


@pytest.mark.asyncio
async def test_unknown_capability_passes_through() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(_req("voice.speak", {"text": "hi"}))
    assert decision.verdict == "allow"
    assert "no schema" in decision.reason


@pytest.mark.asyncio
async def test_head_pose_valid_payload_allows() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(
        _req("head.pose", {"pitch_rad": 0.2, "yaw_rad": -0.4, "duration_ms": 300})
    )
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_head_pose_out_of_range_denies() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(_req("head.pose", {"pitch_rad": 5.0, "yaw_rad": 0.0}))
    assert decision.verdict == "deny"
    assert "pitch_rad" in decision.reason


@pytest.mark.asyncio
async def test_arms_gesture_valid_payload_allows() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(_req("arms.gesture", {"gesture": "high wave"}))
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_arms_gesture_missing_field_denies() -> None:
    policy = PayloadSchemaPolicy()
    decision = await policy.evaluate(_req("arms.gesture", {}))
    assert decision.verdict == "deny"
    assert "gesture" in decision.reason


@pytest.mark.asyncio
async def test_custom_schema_map() -> None:
    class HeadPose(BaseModel):
        pitch_rad: float = Field(ge=-1.0, le=1.0)
        yaw_rad: float = Field(ge=-1.0, le=1.0)

    policy = PayloadSchemaPolicy(schemas={"head.pose": HeadPose})
    ok = await policy.evaluate(_req("head.pose", {"pitch_rad": 0.1, "yaw_rad": 0.0}))
    assert ok.verdict == "allow"

    bad = await policy.evaluate(_req("head.pose", {"pitch_rad": 2.0, "yaw_rad": 0.0}))
    assert bad.verdict == "deny"
    assert "pitch_rad" in bad.reason
