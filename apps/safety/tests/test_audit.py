"""SafetyAuditRecorder tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    RobotCommandRequested,
    SafetyCommandDenied,
    SafetyEStopEngaged,
    SafetyEStopReleased,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import SafetyAuditRecorder
from humanoid_robot.testing import InMemoryEventBus


def _engaged(actor: str = "operator") -> SafetyEStopEngaged:
    return SafetyEStopEngaged(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        actor=actor,
        reason="test",
    )


def _released() -> SafetyEStopReleased:
    return SafetyEStopReleased(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        actor="operator",
    )


def _denied() -> SafetyCommandDenied:
    return SafetyCommandDenied(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id="cmd-1",
        capability="locomotion.move",
        reason="e-stop engaged",
    )


def _requested() -> RobotCommandRequested:
    return RobotCommandRequested(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id="cmd-1",
        capability="locomotion.move",
        payload={"linear_x_mps": 0.3},
    )


@pytest.mark.asyncio
async def test_records_safety_events(tmp_path: Path) -> None:
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=tmp_path / "audit.sqlite")
    await recorder.start()

    await bus.publish(_engaged())
    await bus.publish(_released())
    await bus.publish(_denied())

    records = await recorder.query(subject_prefix="safety.")
    subjects = [r.subject for r in records]
    assert "safety.estop.engaged" in subjects
    assert "safety.estop.released" in subjects
    assert "safety.command.denied" in subjects
    assert await recorder.count() == 3

    await recorder.stop()


@pytest.mark.asyncio
async def test_query_prefix_filter(tmp_path: Path) -> None:
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=tmp_path / "audit.sqlite")
    await recorder.start()

    await bus.publish(_engaged())
    await bus.publish(_requested())

    safety_only = await recorder.query(subject_prefix="safety.")
    robot_only = await recorder.query(subject_prefix="robot.")
    assert {r.subject for r in safety_only} == {"safety.estop.engaged"}
    assert {r.subject for r in robot_only} == {"robot.command.requested"}

    await recorder.stop()


@pytest.mark.asyncio
async def test_query_limit(tmp_path: Path) -> None:
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=tmp_path / "audit.sqlite")
    await recorder.start()

    for i in range(5):
        await bus.publish(_engaged(actor=f"op-{i}"))

    latest_two = await recorder.query(limit=2)
    assert len(latest_two) == 2
    # DESC order — latest actor first
    assert latest_two[0].payload["actor"] == "op-4"
    assert latest_two[1].payload["actor"] == "op-3"

    await recorder.stop()


@pytest.mark.asyncio
async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "audit.sqlite"
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=db)
    await recorder.start()
    await bus.publish(_engaged())
    await recorder.stop()

    reopened = SafetyAuditRecorder(bus=InMemoryEventBus(), db_path=db)
    await reopened.start()
    records = await reopened.query()
    assert len(records) == 1
    await reopened.stop()
