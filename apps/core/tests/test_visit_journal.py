"""Visit journal — SQLite persistence for guard-desk cards."""

from __future__ import annotations

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import VisitCardCompleted
from humanoid_robot.events.base import EventMetadata


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv("HR_VISITS_DB", str(tmp_path / "visits.db"))
    import humanoid_robot.core.visit_journal as vj

    return vj


def _card(**overrides):
    fields = {
        "full_name": "Иванов Иван",
        "organization": "ТОО Тест",
        "purpose": "Встреча",
        "destination": "Отдел кадров",
        "has_pass": True,
        "has_id": None,
    }
    fields.update(overrides)
    return VisitCardCompleted(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        **fields,
    )


def test_insert_and_list(journal) -> None:
    visit_id = journal.insert_visit_sync(_card())
    assert visit_id >= 1
    records = journal.list_visits_sync()
    assert len(records) == 1
    rec = records[0]
    assert rec["full_name"] == "Иванов Иван"
    assert rec["has_pass"] is True
    assert rec["has_id"] is None
    assert rec["status"] == "new"


def test_mark_processed_and_filter(journal) -> None:
    first = journal.insert_visit_sync(_card(full_name="Первый"))
    journal.insert_visit_sync(_card(full_name="Второй"))
    assert journal.mark_processed_sync(first) is True
    assert journal.mark_processed_sync(999) is False
    new_only = journal.list_visits_sync(status="new")
    assert [r["full_name"] for r in new_only] == ["Второй"]
    processed = journal.list_visits_sync(status="processed")
    assert [r["full_name"] for r in processed] == ["Первый"]


def test_newest_first_ordering(journal) -> None:
    for name in ("А", "Б", "В"):
        journal.insert_visit_sync(_card(full_name=name))
    records = journal.list_visits_sync(limit=2)
    assert [r["full_name"] for r in records] == ["В", "Б"]
