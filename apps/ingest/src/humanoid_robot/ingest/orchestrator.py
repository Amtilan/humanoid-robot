"""Ingest orchestrator — parse, chunk, embed, upsert.

Every step is a Port so the same orchestrator can back both the CLI
(directory sweep) and a future inotify-watcher without changes.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from humanoid_robot.domain.knowledge import KnowledgeChunk, KnowledgeSource
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    ChunkerPort,
    DocumentParserPort,
    VectorStorePort,
)

_LOG = get_logger("cortex-ingest.orchestrator")


@dataclass(slots=True, frozen=True)
class IngestSourceResult:
    """Per-file outcome."""

    path: Path
    source: KnowledgeSource | None
    chunks_written: int
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class IngestReport:
    """Aggregate report emitted at the end of a run."""

    total_files: int = 0
    ok_files: int = 0
    failed_files: int = 0
    total_chunks: int = 0
    per_file: list[IngestSourceResult] = field(default_factory=list)
    elapsed_s: float = 0.0


@dataclass(slots=True)
class IngestOrchestrator:
    """Ties Parser → Chunker → VectorStore together."""

    parsers: dict[str, DocumentParserPort]
    chunker: ChunkerPort
    vector_store: VectorStorePort
    chunk_batch_size: int = 64

    async def ingest_path(self, path: Path) -> IngestReport:
        started = time.monotonic()
        report = IngestReport()
        files = list(_walk(path))
        report.total_files = len(files)
        for f in files:
            result = await self._ingest_file(f)
            report.per_file.append(result)
            report.total_chunks += result.chunks_written
            if result.ok:
                report.ok_files += 1
            else:
                report.failed_files += 1
        report.elapsed_s = time.monotonic() - started
        _LOG.info(
            "cortex-ingest.report",
            total=report.total_files,
            ok=report.ok_files,
            failed=report.failed_files,
            chunks=report.total_chunks,
            elapsed_s=round(report.elapsed_s, 3),
        )
        return report

    async def _ingest_file(self, path: Path) -> IngestSourceResult:
        parser = self._parser_for(path)
        if parser is None:
            return IngestSourceResult(
                path=path,
                source=None,
                chunks_written=0,
                ok=False,
                error=f"no parser registered for {path.suffix!r}",
            )
        try:
            source, text = await parser.parse(path)
            chunks_written = await self._chunk_and_upsert(source, text)
        except Exception as exc:
            _LOG.exception("cortex-ingest.file_failed", path=str(path))
            return IngestSourceResult(
                path=path, source=None, chunks_written=0, ok=False, error=str(exc)
            )
        return IngestSourceResult(path=path, source=source, chunks_written=chunks_written, ok=True)

    async def _chunk_and_upsert(self, source: KnowledgeSource, text: str) -> int:
        buffer: list[KnowledgeChunk] = []
        total = 0
        async for chunk in _iter_chunks(self.chunker.chunk(source, text)):
            buffer.append(chunk)
            if len(buffer) >= self.chunk_batch_size:
                await self.vector_store.upsert(tuple(buffer))
                total += len(buffer)
                buffer.clear()
        if buffer:
            await self.vector_store.upsert(tuple(buffer))
            total += len(buffer)
        return total

    def _parser_for(self, path: Path) -> DocumentParserPort | None:
        return self.parsers.get(path.suffix.lower())


async def _iter_chunks(
    it: AsyncIterator[KnowledgeChunk],
) -> AsyncIterator[KnowledgeChunk]:
    async for chunk in it:
        yield chunk


def _walk(root: Path) -> list[Path]:
    """Recursive walk skipping hidden dirs."""
    if root.is_file():
        return [root]
    files: list[Path] = []
    for entry in sorted(root.rglob("*")):
        if any(part.startswith(".") for part in entry.relative_to(root).parts):
            continue
        if entry.is_file():
            files.append(entry)
    return files
