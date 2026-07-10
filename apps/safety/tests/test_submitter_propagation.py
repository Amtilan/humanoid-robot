"""Submitter propagates through the safety gate."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    RobotCommandRequested,
    SafetyCommandDenied,
    SafetyCommandForwarded,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    SafetyGate,
)
from humanoid_robot.testing import InMemoryEventBus


def _request(submitter: str, capability: str = "locomotion.move") -> RobotCommandRequested:
    return RobotCommandRequested(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id=f"cmd-{submitter}",
        capability=capability,
        payload={"linear_x_mps": 0.2, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        submitter=submitter,
    )


@pytest.mark.asyncio
async def test_submitter_flows_into_forwarded() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    await bus.publish(_request("llm"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, SafetyCommandForwarded) for ev in bus.published):
            break

    forwarded = next(ev for ev in bus.published if isinstance(ev, SafetyCommandForwarded))
    assert forwarded.submitter == "llm"

    gate.request_stop()
    await run


@pytest.mark.asyncio
async def test_submitter_flows_into_denial() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=True)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    await bus.publish(_request("plugin:hello"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, SafetyCommandDenied) for ev in bus.published):
            break

    denied = next(ev for ev in bus.published if isinstance(ev, SafetyCommandDenied))
    assert denied.submitter == "plugin:hello"

    gate.request_stop()
    await run


@pytest.mark.asyncio
async def test_missing_submitter_defaults_to_unknown() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    # Direct construction without submitter → default kicks in.
    await bus.publish(
        RobotCommandRequested(
            meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
            command_id="cmd-anon",
            capability="locomotion.move",
            payload={"linear_x_mps": 0.1, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, SafetyCommandForwarded) for ev in bus.published):
            break

    forwarded = next(ev for ev in bus.published if isinstance(ev, SafetyCommandForwarded))
    assert forwarded.submitter == "unknown"

    gate.request_stop()
    await run
