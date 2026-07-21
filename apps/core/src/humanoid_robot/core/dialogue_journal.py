"""Dialogue journal — the robot's full conversation history, persisted.

The dashboard's chat used to live only in the browser's localStorage, so a
page refresh (or a different device) lost almost everything. This journal
subscribes to the dialogue events on the bus — user utterances
(``asr.final``: voice AND typed chat, both flow through it) and the
robot's replies (``llm.answer`` / ``llm.rejected``) — and persists them to
SQLite on the core-state volume. The frontend seeds its chat from
``GET /api/v1/dialogue`` on load, so history survives reloads, browser
switches and robot reboots.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from humanoid_robot.events import AsrFinal, BaseEvent, LlmAnswer, LlmRejected
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-core.dialogue")

# Keep the journal bounded: prune the oldest rows past this many.
_MAX_ROWS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done'
)
"""


def _db_path() -> Path:
    # Resolved per call so tests can point HR_DIALOGUE_DB at a tmp dir.
    return Path(os.environ.get("HR_DIALOGUE_DB", "/var/lib/humanoid-robot/dialogue.db"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def insert_message_sync(*, session_id: str, role: str, text: str, status: str = "done") -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO dialogue (created_at, session_id, role, text, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                session_id,
                role,
                text,
                status,
            ),
        )
        conn.execute(
            "DELETE FROM dialogue WHERE id <= ( SELECT COALESCE(MAX(id), 0) - ? FROM dialogue)",
            (_MAX_ROWS,),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def list_messages_sync(limit: int = 200) -> list[dict[str, Any]]:
    """The most recent messages, oldest-first (chat display order)."""
    limit = max(1, min(int(limit), 1000))
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM dialogue ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


def clear_sync() -> int:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM dialogue")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


class DialogueJournal:
    """Bus subscriber that persists the conversation."""

    async def start(self, bus: EventBusPort) -> list[Subscription]:
        return [
            await bus.subscribe(AsrFinal.subject, self._on_event),
            await bus.subscribe(LlmAnswer.subject, self._on_event),
            await bus.subscribe(LlmRejected.subject, self._on_event),
        ]

    async def _on_event(self, event: BaseEvent) -> None:
        row: tuple[str, str, str, str] | None = None
        if isinstance(event, AsrFinal) and event.text.strip():
            row = (event.session_id, "user", event.text.strip(), "done")
        elif isinstance(event, LlmAnswer) and event.text.strip():
            row = (event.session_id, "assistant", event.text.strip(), "done")
        elif isinstance(event, LlmRejected):
            text = (event.fallback_text or "").strip() or event.reason
            row = (event.session_id, "assistant", text, "rejected")
        if row is None:
            return
        session_id, role, text, status = row
        try:
            await asyncio.to_thread(
                insert_message_sync,
                session_id=session_id,
                role=role,
                text=text,
                status=status,
            )
        except Exception:
            _LOG.exception("dialogue_journal.insert_failed")
