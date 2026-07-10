"""Audit rotation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import SafetyEStopEngaged
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import SafetyAuditRecorder
from humanoid_robot.testing import InMemoryEventBus


def _engaged(actor: str = "operator") -> SafetyEStopEngaged:
    return SafetyEStopEngaged(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        actor=actor,
        reason="test",
    )


@pytest.mark.asyncio
async def test_max_rows_prunes_oldest(tmp_path: Path) -> None:
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(
        bus=bus,
        db_path=tmp_path / "audit.sqlite",
        max_rows=3,
        rotation_interval_s=60.0,  # rely on manual prune_once() in the test
    )
    await recorder.start()

    for i in range(5):
        await bus.publish(_engaged(actor=f"op-{i}"))

    assert await recorder.count() == 5
    deleted = await recorder.prune_once()
    assert deleted == 2
    remaining = await recorder.query(limit=10)
    assert [r.payload["actor"] for r in remaining] == ["op-4", "op-3", "op-2"]

    await recorder.stop()


@pytest.mark.asyncio
async def test_max_age_prunes_old_rows(tmp_path: Path) -> None:
    db = tmp_path / "audit.sqlite"
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=db, max_age_days=1.0, rotation_interval_s=60.0)
    await recorder.start()

    # Insert one row directly-dated in the past, one fresh.
    old_iso = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    fresh_iso = datetime.now(UTC).isoformat()
    assert recorder._connection is not None  # test-only inspection
    conn = recorder._connection
    await conn.execute(
        "INSERT INTO audit_events (occurred_at, subject, correlation_id, producer, "
        "payload_json) VALUES (?, ?, ?, ?, ?)",
        (old_iso, "safety.estop.engaged", "cid-old", "tests", "{}"),
    )
    await conn.execute(
        "INSERT INTO audit_events (occurred_at, subject, correlation_id, producer, "
        "payload_json) VALUES (?, ?, ?, ?, ?)",
        (fresh_iso, "safety.estop.engaged", "cid-fresh", "tests", "{}"),
    )
    await conn.commit()

    assert await recorder.count() == 2
    deleted = await recorder.prune_once()
    assert deleted == 1
    remaining = await recorder.query(limit=10)
    assert [r.correlation_id for r in remaining] == ["cid-fresh"]

    await recorder.stop()


@pytest.mark.asyncio
async def test_no_rotation_when_thresholds_none(tmp_path: Path) -> None:
    bus = InMemoryEventBus()
    recorder = SafetyAuditRecorder(bus=bus, db_path=tmp_path / "audit.sqlite")
    await recorder.start()

    for i in range(3):
        await bus.publish(_engaged(actor=f"op-{i}"))

    deleted = await recorder.prune_once()
    assert deleted == 0
    assert await recorder.count() == 3

    await recorder.stop()
