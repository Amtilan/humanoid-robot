"""KnowledgeService tests using in-memory fakes."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from humanoid_robot.core.knowledge_service import (
    KnowledgeNotConfiguredError,
    KnowledgeService,
)
from humanoid_robot.domain.knowledge import KnowledgeChunk, RetrievalHit
from humanoid_robot.ports import KnowledgeSourceSummary
from humanoid_robot.ports.knowledge import RetrievalQuery


@dataclass(slots=True)
class _FakeStore:
    scripted_summaries: tuple[KnowledgeSourceSummary, ...]
    deleted: list[str] = field(default_factory=list)

    async def upsert(self, _chunks: tuple[KnowledgeChunk, ...]) -> None:
        return

    async def delete_by_source(self, source_id: str) -> None:
        self.deleted.append(source_id)

    async def search(self, _q: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        return ()

    async def list_sources(self) -> tuple[KnowledgeSourceSummary, ...]:
        return self.scripted_summaries

    async def close(self) -> None:
        return


class TestKnowledgeService:
    async def test_unconfigured_returns_empty_and_raises_on_delete(self) -> None:
        service = KnowledgeService()
        assert not service.is_configured()
        assert await service.list_sources() == ()
        with pytest.raises(KnowledgeNotConfiguredError):
            await service.delete_source("s1")

    async def test_configured_lists_sources_from_store(self) -> None:
        store = _FakeStore(
            scripted_summaries=(
                KnowledgeSourceSummary(source_id="s1", chunk_count=3),
                KnowledgeSourceSummary(source_id="s2", chunk_count=1),
            )
        )
        service = KnowledgeService(vector_store=store)
        assert service.is_configured()
        summaries = await service.list_sources()
        assert [s.source_id for s in summaries] == ["s1", "s2"]

    async def test_delete_forwards_to_store(self) -> None:
        store = _FakeStore(scripted_summaries=())
        service = KnowledgeService(vector_store=store)
        await service.delete_source("s42")
        assert store.deleted == ["s42"]

    def test_jobs_starts_empty(self) -> None:
        service = KnowledgeService()
        assert service.jobs() == []
        assert service.get_job("nope") is None
