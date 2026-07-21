"""Dialogue journal — persisted conversation history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("HR_DIALOGUE_DB", str(tmp_path / "dialogue.db"))
    import humanoid_robot.core.dialogue_journal as dj

    return dj


def test_insert_and_list_in_display_order(journal: Any) -> None:
    journal.insert_message_sync(session_id="s1", role="user", text="привет")
    journal.insert_message_sync(session_id="s1", role="assistant", text="здравствуйте")
    records = journal.list_messages_sync()
    assert [(r["role"], r["text"]) for r in records] == [
        ("user", "привет"),
        ("assistant", "здравствуйте"),
    ]


def test_limit_returns_most_recent(journal: Any) -> None:
    for i in range(5):
        journal.insert_message_sync(session_id="s", role="user", text=f"m{i}")
    records = journal.list_messages_sync(limit=2)
    assert [r["text"] for r in records] == ["m3", "m4"]


def test_clear(journal: Any) -> None:
    journal.insert_message_sync(session_id="s", role="user", text="x")
    assert journal.clear_sync() == 1
    assert journal.list_messages_sync() == []
