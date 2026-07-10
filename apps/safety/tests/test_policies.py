"""Policy unit tests."""

from __future__ import annotations

import asyncio
import time

import pytest

from humanoid_robot.ports import SafetyRequest
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    RateLimitPolicy,
)


def _req(capability: str = "locomotion.move") -> SafetyRequest:
    return SafetyRequest(command_id="cmd-1", capability=capability, payload={})


@pytest.mark.asyncio
async def test_estop_engaged_denies() -> None:
    policy = EStopPolicy(EStopState(engaged=True))
    decision = await policy.evaluate(_req())
    assert decision.verdict == "deny"


@pytest.mark.asyncio
async def test_estop_released_allows() -> None:
    policy = EStopPolicy(EStopState(engaged=False))
    decision = await policy.evaluate(_req())
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_known_capabilities_deny_by_default() -> None:
    policy = KnownCapabilitiesPolicy(allowed=frozenset())
    decision = await policy.evaluate(_req())
    assert decision.verdict == "deny"


@pytest.mark.asyncio
async def test_known_capabilities_allow_listed() -> None:
    policy = KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"}))
    decision = await policy.evaluate(_req())
    assert decision.verdict == "allow"


@pytest.mark.asyncio
async def test_rate_limit_denies_after_burst() -> None:
    policy = RateLimitPolicy(window_s=60.0, max_events=2)
    assert (await policy.evaluate(_req())).verdict == "allow"
    assert (await policy.evaluate(_req())).verdict == "allow"
    denial = await policy.evaluate(_req())
    assert denial.verdict == "deny"


@pytest.mark.asyncio
async def test_rate_limit_expires_after_window() -> None:
    policy = RateLimitPolicy(window_s=0.02, max_events=1)
    assert (await policy.evaluate(_req())).verdict == "allow"
    assert (await policy.evaluate(_req())).verdict == "deny"
    await asyncio.sleep(0.05)
    assert (await policy.evaluate(_req())).verdict == "allow"


@pytest.mark.asyncio
async def test_chain_first_deny_wins() -> None:
    policy = ChainPolicy(
        [
            KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
            EStopPolicy(EStopState(engaged=True)),
        ]
    )
    decision = await policy.evaluate(_req())
    assert decision.verdict == "deny"
    assert "e-stop" in decision.reason.lower()


@pytest.mark.asyncio
async def test_chain_empty_denies() -> None:
    decision = await ChainPolicy([]).evaluate(_req())
    assert decision.verdict == "deny"


@pytest.mark.asyncio
async def test_chain_all_allow() -> None:
    policy = ChainPolicy(
        [
            KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
            EStopPolicy(EStopState(engaged=False)),
        ]
    )
    decision = await policy.evaluate(_req())
    assert decision.verdict == "allow"


def test_time_source_available() -> None:
    """Sanity check — dependency on monotonic clock."""
    assert time.monotonic() > 0
