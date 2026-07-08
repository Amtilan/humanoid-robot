"""QdrantLocalStore tests with an injected fake client + fake embedder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from humanoid_robot.adapters.vector_qdrant import (
    QdrantConfig,
    QdrantLocalStore,
    QdrantRuntimeNotAvailableError,
)
from humanoid_robot.domain.knowledge import KnowledgeChunk
from humanoid_robot.ports.knowledge import RetrievalQuery


@dataclass(slots=True)
class _FakeEmbedder:
    dim: int = 4

    @property
    def dimension(self) -> int:
        return self.dim

    async def embed_dense(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((float(len(t)),) * self.dim for t in texts)

    async def embed_sparse(self, texts: tuple[str, ...]) -> tuple[dict[int, float], ...]:
        return tuple({0: 1.0} for _ in texts)


@dataclass(slots=True)
class _FakeQdrant:
    upserts: list[list[dict[str, Any]]] = field(default_factory=list)
    deletes: list[Any] = field(default_factory=list)
    scripted_hits: list[Any] = field(default_factory=list)
    closed: bool = False

    def get_collection(self, _name: str) -> None:
        # Return None to signal it exists.
        return None

    def upsert(self, *, collection_name: str, points: list[dict[str, Any]]) -> None:
        del collection_name
        self.upserts.append(points)

    def delete(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)

    def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: Any,
    ) -> list[Any]:
        del collection_name, query_vector, limit, query_filter
        return list(self.scripted_hits)

    def close(self) -> None:
        self.closed = True


def _loader(fake: _FakeQdrant) -> Callable[..., _FakeQdrant]:
    def _mk(_: QdrantConfig) -> _FakeQdrant:
        return fake

    return _mk


def _chunk(id_: str = "c1", content: str = "hello world") -> KnowledgeChunk:
    return KnowledgeChunk(id=id_, source_id="s1", ordinal=0, content=content, token_count=2)


class TestQdrantLocalStore:
    async def test_missing_runtime_raises(self) -> None:
        store = QdrantLocalStore(config=QdrantConfig(), embedder=_FakeEmbedder())
        with pytest.raises(QdrantRuntimeNotAvailableError):
            await store.upsert((_chunk(),))

    async def test_upsert_batches_and_embeds(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(upsert_batch_size=2, dense_dim=64),
            embedder=_FakeEmbedder(dim=64),
            loader=_loader(fake),
        )
        chunks = tuple(_chunk(f"c{i}") for i in range(5))
        await store.upsert(chunks)
        # 5 chunks, batch size 2 → 3 batches: [2, 2, 1].
        assert [len(b) for b in fake.upserts] == [2, 2, 1]
        # Each point carries the source id in the payload.
        assert fake.upserts[0][0]["payload"]["source_id"] == "s1"

    async def test_search_returns_retrieval_hits(self) -> None:
        fake = _FakeQdrant(
            scripted_hits=[
                SimpleNamespace(
                    id="c1",
                    score=0.9,
                    payload={
                        "chunk_id": "c1",
                        "source_id": "s1",
                        "content": "answer text",
                        "ordinal": 0,
                    },
                ),
                SimpleNamespace(
                    id="c2",
                    score=0.4,
                    payload={
                        "chunk_id": "c2",
                        "source_id": "s1",
                        "content": "other",
                        "ordinal": 1,
                    },
                ),
            ]
        )
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        hits = await store.search(RetrievalQuery(text="what?"))
        assert len(hits) == 2
        assert hits[0].chunk.id == "c1"
        assert hits[0].dense_score == pytest.approx(0.9)
        assert hits[0].chunk.content == "answer text"

    async def test_delete_by_source_uses_filter(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        await store.delete_by_source("s42")
        assert fake.deletes
        selector = fake.deletes[0]["points_selector"]
        assert selector["filter"]["must"][0]["match"]["value"] == "s42"

    async def test_close_calls_client_close(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        # Force client creation by touching a method.
        await store.delete_by_source("s1")
        await store.close()
        assert fake.closed
