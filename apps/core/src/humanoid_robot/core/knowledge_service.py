"""Read-only knowledge introspection + background ingest jobs.

`cortex-core` does not, itself, embed or upsert — that is `cortex-ingest`'s
job.  What we do here:

- Expose whatever a `VectorStorePort` implementation was wired in through
  `list_sources()` and `delete_by_source(...)`.
- Optionally launch an ingest run as a subprocess so an operator can
  trigger it from the UI (jobs tracked in an in-memory map).

If no vector store is bound (e.g. cortex-core running without the
knowledge extras installed), `list_sources` returns an empty tuple and
delete returns a helpful error so the UI can render "not configured".
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from humanoid_robot.domain.shared import Timestamp
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import KnowledgeSourceSummary, VectorStorePort

_LOG = get_logger("cortex-core.knowledge_service")


class KnowledgeNotConfiguredError(RuntimeError):
    """The container has no vector store bound."""


class IngestJobStatus(BaseModel):
    """Progress of an operator-triggered ingest run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    directory: str
    state: str  # "running" | "succeeded" | "failed"
    started_at: Timestamp
    finished_at: Timestamp | None = None
    exit_code: int | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None


@dataclass(slots=True)
class KnowledgeService:
    """Owns knowledge-facing endpoints for cortex-core."""

    vector_store: VectorStorePort | None = None
    _jobs: dict[str, IngestJobStatus] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_configured(self) -> bool:
        return self.vector_store is not None

    async def list_sources(self) -> tuple[KnowledgeSourceSummary, ...]:
        if self.vector_store is None:
            return ()
        return await self.vector_store.list_sources()

    async def delete_source(self, source_id: str) -> None:
        if self.vector_store is None:
            msg = "no vector store is bound to cortex-core"
            raise KnowledgeNotConfiguredError(msg)
        await self.vector_store.delete_by_source(source_id)

    def jobs(self) -> list[IngestJobStatus]:
        return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    def get_job(self, job_id: str) -> IngestJobStatus | None:
        return self._jobs.get(job_id)

    async def start_ingest_job(
        self,
        *,
        directory: str,
        config_path: str,
    ) -> IngestJobStatus:
        """Launch `cortex-ingest run` as a subprocess and track it."""
        async with self._lock:
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            started = datetime.now(tz=UTC)
            status = IngestJobStatus(
                id=job_id,
                directory=directory,
                state="running",
                started_at=started,
            )
            self._jobs[job_id] = status

        task = asyncio.create_task(
            self._run_job(
                job_id=job_id,
                directory=directory,
                config_path=config_path,
            ),
            name=f"ingest-job[{job_id}]",
        )
        task.add_done_callback(_log_task_error)
        return status

    async def _run_job(self, *, job_id: str, directory: str, config_path: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "cortex-ingest",
                "run",
                "--config",
                config_path,
                "--dir",
                directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()
            state = "succeeded" if process.returncode == 0 else "failed"
            self._jobs[job_id] = IngestJobStatus(
                id=job_id,
                directory=directory,
                state=state,
                started_at=self._jobs[job_id].started_at,
                finished_at=datetime.now(tz=UTC),
                exit_code=process.returncode,
                stdout_tail=_tail(stdout_bytes),
                stderr_tail=_tail(stderr_bytes),
            )
        except Exception as exc:
            _LOG.exception("knowledge_service.ingest_job_failed", job=job_id)
            self._jobs[job_id] = IngestJobStatus(
                id=job_id,
                directory=directory,
                state="failed",
                started_at=self._jobs[job_id].started_at,
                finished_at=datetime.now(tz=UTC),
                exit_code=None,
                stderr_tail=str(exc),
            )


def _tail(data: bytes | None, *, limit: int = 4000) -> str | None:
    if not data:
        return None
    text = data.decode(errors="replace")
    if len(text) <= limit:
        return text
    return "…\n" + text[-limit:]


def _log_task_error(task: asyncio.Task[None]) -> None:
    exc = task.exception()
    if exc is not None:
        _LOG.error("knowledge_service.task_error", error=str(exc))
