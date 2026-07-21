"""Event journal — a bounded, persisted tail of the platform event bus.

Every dev console page (Events, Voice sessions, …) used to build its view
from LIVE WebSocket events only, so a page refresh started from blank.
This journal subscribes to the whole bus, skips the high-rate firehose
subjects, and keeps the last few thousand envelopes in SQLite on the
core-state volume; ``GET /api/v1/events/history`` replays them to a
freshly-opened page.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from humanoid_robot.events import BaseEvent
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-core.event_journal")

# High-rate subjects that would drown the journal in noise. The pages that
# need them (mic monitor, streaming chat, telemetry gauges) are live-only by
# design; the *final* llm.answer / asr.final still land in the journal.
_SKIP_SUBJECTS = frozenset(
    {
        "audio.monitor.frame",
        "audio.monitor.control",
        "llm.answer.token",
        "robot.telemetry",
        "system.diagnostics.tick",
    }
)

_MAX_ROWS = 4000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    event_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL DEFAULT '',
    producer TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL
)
"""


def _db_path() -> Path:
    return Path(os.environ.get("HR_EVENTS_DB", "/var/lib/humanoid-robot/events.db"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def insert_event_sync(
    *,
    subject: str,
    event_id: str,
    occurred_at: str,
    correlation_id: str,
    producer: str,
    data: dict[str, Any],
) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO events (subject, event_id, occurred_at, correlation_id,"
            " producer, data) VALUES (?, ?, ?, ?, ?, ?)",
            (
                subject,
                event_id,
                occurred_at,
                correlation_id,
                producer,
                json.dumps(data, ensure_ascii=False),
            ),
        )
        conn.execute(
            "DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id), 0) - ? FROM events)",
            (_MAX_ROWS,),
        )
        conn.commit()
    finally:
        conn.close()


def list_events_sync(limit: int = 500, subject_prefix: str = "") -> list[dict[str, Any]]:
    """The most recent envelopes, oldest-first (replay order)."""
    limit = max(1, min(int(limit), 2000))
    query = "SELECT * FROM events"
    params: list[Any] = []
    if subject_prefix:
        query += " WHERE subject LIKE ?"
        params.append(subject_prefix.replace("%", "") + "%")
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    records = []
    for row in reversed(rows):
        d = dict(row)
        try:
            d["data"] = json.loads(d["data"])
        except ValueError:
            d["data"] = {}
        d.pop("id", None)
        records.append(d)
    return records


class EventJournal:
    """Bus subscriber persisting a bounded tail of (almost) all events."""

    async def start(self, bus: EventBusPort) -> Subscription:
        return await bus.subscribe(">", self._on_event)

    async def _on_event(self, event: BaseEvent) -> None:
        subject = type(event).subject
        if subject in _SKIP_SUBJECTS:
            return
        try:
            await asyncio.to_thread(
                insert_event_sync,
                subject=subject,
                event_id=event.meta.event_id,
                occurred_at=event.meta.occurred_at.isoformat(),
                correlation_id=event.meta.correlation_id,
                producer=event.meta.producer,
                data=event.model_dump(mode="json", exclude={"meta"}),
            )
        except Exception:
            _LOG.exception("event_journal.insert_failed", subject=subject)
