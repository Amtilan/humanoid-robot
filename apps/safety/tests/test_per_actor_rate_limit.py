"""PerActorRateLimitPolicy tests."""

from __future__ import annotations

import pytest

from humanoid_robot.ports import SafetyRequest
from humanoid_robot.safety import ActorRateLimit, PerActorRateLimitPolicy


def _req(submitter: str) -> SafetyRequest:
    return SafetyRequest(
        command_id="cmd-1",
        capability="locomotion.move",
        payload={},
        submitter=submitter,
    )


@pytest.mark.asyncio
async def test_operator_uses_own_budget() -> None:
    policy = PerActorRateLimitPolicy(
        limits={
            "operator": ActorRateLimit(window_s=60.0, max_events=3),
            "llm": ActorRateLimit(window_s=60.0, max_events=1),
        },
        default=ActorRateLimit(window_s=60.0, max_events=0),
    )
    for _ in range(3):
        assert (await policy.evaluate(_req("operator"))).verdict == "allow"
    denial = await policy.evaluate(_req("operator"))
    assert denial.verdict == "deny"
    assert "operator" in denial.reason


@pytest.mark.asyncio
async def test_llm_hits_its_own_cap_independently() -> None:
    policy = PerActorRateLimitPolicy(
        limits={
            "operator": ActorRateLimit(window_s=60.0, max_events=10),
            "llm": ActorRateLimit(window_s=60.0, max_events=1),
        },
        default=ActorRateLimit(window_s=60.0, max_events=0),
    )
    assert (await policy.evaluate(_req("llm"))).verdict == "allow"
    denial = await policy.evaluate(_req("llm"))
    assert denial.verdict == "deny"
    # operator is untouched by llm's counter
    assert (await policy.evaluate(_req("operator"))).verdict == "allow"


@pytest.mark.asyncio
async def test_unknown_actor_uses_default_bucket() -> None:
    policy = PerActorRateLimitPolicy(
        limits={"operator": ActorRateLimit(window_s=60.0, max_events=10)},
        default=ActorRateLimit(window_s=60.0, max_events=2),
    )
    assert (await policy.evaluate(_req("random-source"))).verdict == "allow"
    assert (await policy.evaluate(_req("random-source"))).verdict == "allow"
    denial = await policy.evaluate(_req("random-source"))
    assert denial.verdict == "deny"


@pytest.mark.asyncio
async def test_default_zero_budget_denies_unknown() -> None:
    policy = PerActorRateLimitPolicy(
        limits={"operator": ActorRateLimit(window_s=60.0, max_events=1)},
        default=ActorRateLimit(window_s=60.0, max_events=0),
    )
    denial = await policy.evaluate(_req("mystery"))
    assert denial.verdict == "deny"
    assert "no command budget" in denial.reason
