"""Event journal — persisted bus tail for page reloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("HR_EVENTS_DB", str(tmp_path / "events.db"))
    import humanoid_robot.core.event_journal as ej

    return ej


def _insert(journal: Any, subject: str, event_id: str) -> None:
    journal.insert_event_sync(
        subject=subject,
        event_id=event_id,
        occurred_at="2026-07-21T10:00:00+00:00",
        correlation_id="cor_x",
        producer="tests",
        data={"text": "привет"},
    )


def test_insert_and_replay_order(journal: Any) -> None:
    _insert(journal, "asr.final", "evt_1")
    _insert(journal, "llm.answer", "evt_2")
    records = journal.list_events_sync()
    assert [r["event_id"] for r in records] == ["evt_1", "evt_2"]
    assert records[0]["data"] == {"text": "привет"}


def test_subject_prefix_filter(journal: Any) -> None:
    _insert(journal, "asr.final", "evt_1")
    _insert(journal, "tts.synth.started", "evt_2")
    records = journal.list_events_sync(subject_prefix="tts.")
    assert [r["subject"] for r in records] == ["tts.synth.started"]


def test_bounded(journal: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal, "_MAX_ROWS", 3)
    for i in range(6):
        _insert(journal, "asr.final", f"evt_{i}")
    records = journal.list_events_sync()
    assert len(records) == 3
    assert records[-1]["event_id"] == "evt_5"
