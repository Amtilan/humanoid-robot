"""Persistent audit log for safety-relevant events.

Writes each ``safety.*`` and ``robot.command.*`` event to a SQLite
database file so operators can replay incidents after the fact.  The
recorder never blocks the bus — persistence errors are logged and
swallowed, matching the fail-closed spirit (the gate still works even
if the disk is full).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite
from pydantic import BaseModel, ConfigDict

from humanoid_robot.events import BaseEvent
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-safety.audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    producer TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject_occurred_at
    ON audit_events(subject, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at
    ON audit_events(occurred_at);
"""

_DEFAULT_SUBJECTS: tuple[str, ...] = (
    "safety.estop.engaged",
    "safety.estop.released",
    "safety.command.denied",
    "safety.command.forwarded",
    "safety.command.timeout",
    "safety.watchdog.heartbeat",
    "robot.command.requested",
    "robot.command.result",
)


class AuditRecord(BaseModel):
    """One row from the audit table (read model)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    occurred_at: str
    subject: str
    correlation_id: str
    producer: str
    payload: dict[str, object]


@dataclass(slots=True)
class SafetyAuditRecorder:
    """Subscribes to safety-adjacent subjects and persists them."""

    bus: EventBusPort
    db_path: Path
    subjects: tuple[str, ...] = _DEFAULT_SUBJECTS
    _connection: aiosqlite.Connection | None = None
    _subscriptions: list[Subscription] = field(default_factory=list)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if self._connection is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        await conn.executescript(_SCHEMA)
        await conn.commit()
        self._connection = conn
        for subject in self.subjects:
            sub = await self.bus.subscribe(subject, self._on_event)
            self._subscriptions.append(sub)
        _LOG.info("audit.ready", db=str(self.db_path), subjects=list(self.subjects))

    async def stop(self) -> None:
        for sub in self._subscriptions:
            with contextlib.suppress(Exception):
                await sub.cancel()
        self._subscriptions.clear()
        if self._connection is not None:
            with contextlib.suppress(Exception):
                await self._connection.close()
            self._connection = None

    async def _on_event(self, event: BaseEvent) -> None:
        payload = event.model_dump(mode="json", exclude={"meta"})
        row = (
            event.meta.occurred_at.isoformat(),
            type(event).subject,
            event.meta.correlation_id,
            event.meta.producer,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        try:
            async with self._write_lock:
                conn = self._connection
                if conn is None:
                    return
                await conn.execute(
                    "INSERT INTO audit_events "
                    "(occurred_at, subject, correlation_id, producer, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    row,
                )
                await conn.commit()
        except Exception:
            _LOG.exception("audit.write_failed", subject=row[1])

    async def query(
        self,
        *,
        subject_prefix: str | None = None,
        since_iso: str | None = None,
        limit: int = 100,
    ) -> tuple[AuditRecord, ...]:
        conn = self._connection
        if conn is None:
            return ()
        clauses: list[str] = []
        params: list[object] = []
        if subject_prefix:
            clauses.append("subject LIKE ?")
            params.append(f"{subject_prefix}%")
        if since_iso:
            clauses.append("occurred_at >= ?")
            params.append(since_iso)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # `where` is composed only from module-private static clauses; all
        # user-supplied values are bound as ? params.
        query = f"SELECT id, occurred_at, subject, correlation_id, producer, payload_json FROM audit_events {where} ORDER BY id DESC LIMIT ?"  # noqa: S608
        params.append(max(1, min(limit, 1_000)))
        async with self._write_lock:
            rows = await conn.execute_fetchall(query, tuple(params))
        return tuple(_row_to_record(row) for row in rows)

    async def count(self) -> int:
        conn = self._connection
        if conn is None:
            return 0
        async with self._write_lock:
            rows = await conn.execute_fetchall("SELECT COUNT(*) FROM audit_events")
        row = rows[0] if rows else (0,)
        return int(row[0])


def _row_to_record(row: Iterable[object]) -> AuditRecord:
    values = tuple(row)
    return AuditRecord(
        id=int(values[0]),  # type: ignore[arg-type]
        occurred_at=str(values[1]),
        subject=str(values[2]),
        correlation_id=str(values[3]),
        producer=str(values[4]),
        payload=json.loads(str(values[5])),
    )
