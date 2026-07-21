"""Visit journal — persists completed visitor cards from the bus.

The rag interview publishes ``visit.card.completed``; this journal stores
every card in SQLite on the core-state volume so the guard panel and the
REST API (``/api/v1/visits``) survive restarts. All sqlite work runs in a
worker thread — the event loop never blocks on disk.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from humanoid_robot.events import BaseEvent, VisitCardCompleted
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-core.visits")


def _db_path() -> Path:
    # Resolved per call so tests can point HR_VISITS_DB at a tmp dir.
    return Path(os.environ.get("HR_VISITS_DB", "/var/lib/humanoid-robot/visits.db"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT '',
    has_pass INTEGER,
    has_id INTEGER,
    status TEXT NOT NULL DEFAULT 'new'
)
"""


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def _to_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("has_pass", "has_id"):
        d[key] = None if d[key] is None else bool(d[key])
    return d


def insert_visit_sync(event: VisitCardCompleted) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO visits (created_at, language, full_name, organization,"
            " purpose, destination, has_pass, has_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                event.language,
                event.full_name,
                event.organization,
                event.purpose,
                event.destination,
                _to_int(event.has_pass),
                _to_int(event.has_id),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def list_visits_sync(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    query = "SELECT * FROM visits"
    params: list[Any] = []
    if status in ("new", "processed"):
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def mark_processed_sync(visit_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("UPDATE visits SET status = 'processed' WHERE id = ?", (int(visit_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


class VisitJournal:
    """Bus subscriber that persists completed visit cards."""

    async def start(self, bus: EventBusPort) -> Subscription:
        return await bus.subscribe(VisitCardCompleted.subject, self._on_completed)

    async def _on_completed(self, event: BaseEvent) -> None:
        if not isinstance(event, VisitCardCompleted):
            return
        try:
            visit_id = await asyncio.to_thread(insert_visit_sync, event)
        except Exception:
            _LOG.exception("visit_journal.insert_failed")
            return
        _LOG.info("visit_journal.recorded", visit_id=visit_id, full_name=event.full_name)
