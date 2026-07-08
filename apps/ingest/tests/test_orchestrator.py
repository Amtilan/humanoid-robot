"""IngestOrchestrator end-to-end tests with fake ports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from humanoid_robot.adapters.parser_basic import TextParser
from humanoid_robot.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeSource,
    RetrievalHit,
)
from humanoid_robot.ingest import IngestOrchestrator
from humanoid_robot.ports.knowledge import KnowledgeSourceSummary, RetrievalQuery


@dataclass(slots=True)
class _FakeChunker:
    chunk_size: int = 20  # chars

    def chunk(self, source: KnowledgeSource, text: str) -> AsyncIterator[KnowledgeChunk]:
        async def _gen() -> AsyncIterator[KnowledgeChunk]:
            for i in range(0, len(text), self.chunk_size):
                chunk_text = text[i : i + self.chunk_size]
                yield KnowledgeChunk(
                    id=f"{source.id}-{i}",
                    source_id=source.id,
                    ordinal=i // self.chunk_size,
                    content=chunk_text,
                    token_count=len(chunk_text) // 4,
                )

        return _gen()


@dataclass(slots=True)
class _FakeStore:
    upsert_batches: list[tuple[KnowledgeChunk, ...]] = field(default_factory=list)
    closed: bool = False

    async def upsert(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        self.upsert_batches.append(chunks)

    async def delete_by_source(self, _source_id: str) -> None:
        return

    async def search(self, _query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        return ()

    async def list_sources(self) -> tuple[KnowledgeSourceSummary, ...]:
        return ()

    async def close(self) -> None:
        self.closed = True


class TestIngestOrchestrator:
    async def test_single_file_ingested_end_to_end(self, tmp_path: Path) -> None:
        f = tmp_path / "note.txt"
        f.write_text("Hello robot planet." * 10, encoding="utf-8")
        store = _FakeStore()
        orch = IngestOrchestrator(
            parsers={".txt": TextParser()},
            chunker=_FakeChunker(),
            vector_store=store,
            chunk_batch_size=8,
        )
        report = await orch.ingest_path(f)
        assert report.total_files == 1
        assert report.ok_files == 1
        assert report.failed_files == 0
        assert report.total_chunks > 0
        assert store.upsert_batches

    async def test_directory_walk_ingests_all_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("A" * 40, encoding="utf-8")
        (tmp_path / "b.txt").write_text("B" * 60, encoding="utf-8")
        (tmp_path / "ignored.bin").write_text("ignored", encoding="utf-8")
        # Hidden dirs should be skipped.
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "c.txt").write_text("skip", encoding="utf-8")

        store = _FakeStore()
        orch = IngestOrchestrator(
            parsers={".txt": TextParser()},
            chunker=_FakeChunker(),
            vector_store=store,
        )
        report = await orch.ingest_path(tmp_path)
        assert report.total_files == 3  # a.txt, b.txt, ignored.bin
        assert report.ok_files == 2  # only the two .txt files
        assert report.failed_files == 1
        assert any("no parser" in (r.error or "") for r in report.per_file)

    async def test_upserts_are_batched(self, tmp_path: Path) -> None:
        f = tmp_path / "large.txt"
        # 40 chars per chunk * many chunks vs batch size 8.
        f.write_text("X" * 400, encoding="utf-8")
        store = _FakeStore()
        orch = IngestOrchestrator(
            parsers={".txt": TextParser()},
            chunker=_FakeChunker(chunk_size=20),
            vector_store=store,
            chunk_batch_size=4,
        )
        report = await orch.ingest_path(f)
        assert report.ok_files == 1
        assert all(len(b) <= 4 for b in store.upsert_batches)

    async def test_missing_parser_reported_but_does_not_crash(self, tmp_path: Path) -> None:
        f = tmp_path / "foo.xyz"
        f.write_text("bytes", encoding="utf-8")
        store = _FakeStore()
        orch = IngestOrchestrator(
            parsers={".txt": TextParser()},
            chunker=_FakeChunker(),
            vector_store=store,
        )
        report = await orch.ingest_path(f)
        assert report.total_files == 1
        assert report.failed_files == 1
        assert "no parser" in (report.per_file[0].error or "")
