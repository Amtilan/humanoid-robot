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
    sparse_available: bool = True

    @property
    def dimension(self) -> int:
        return self.dim

    async def embed_dense(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((float(len(t)),) * self.dim for t in texts)

    async def embed_sparse(self, texts: tuple[str, ...]) -> tuple[dict[int, float], ...]:
        if not self.sparse_available:
            raise NotImplementedError
        return tuple({0: 1.0, 1: 0.5} for _ in texts)


@dataclass(slots=True)
class _FakeQdrant:
    upserts: list[list[dict[str, Any]]] = field(default_factory=list)
    deletes: list[Any] = field(default_factory=list)
    dense_hits: list[Any] = field(default_factory=list)
    sparse_hits: list[Any] = field(default_factory=list)
    scroll_pages: list[list[Any]] = field(default_factory=list)
    closed: bool = False
    search_calls: list[dict[str, Any]] = field(default_factory=list)

    def get_collection(self, _name: str) -> None:
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
        query_vector: Any,
        limit: int,
        query_filter: Any,
    ) -> list[Any]:
        del collection_name, query_filter
        # Route by named-vector prefix.
        name = query_vector[0] if isinstance(query_vector, tuple) else None
        self.search_calls.append({"vector": name, "limit": limit})
        if name == "sparse":
            return list(self.sparse_hits)
        return list(self.dense_hits)

    def scroll(
        self,
        *,
        collection_name: str,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
        offset: Any,
    ) -> tuple[list[Any], Any]:
        del collection_name, limit, with_payload, with_vectors
        # If the fake was seeded with pages, page through them.
        pages = self.scroll_pages
        index = offset or 0
        if index >= len(pages):
            return ([], None)
        next_offset = index + 1 if index + 1 < len(pages) else None
        return (pages[index], next_offset)

    def close(self) -> None:
        self.closed = True


def _loader(fake: _FakeQdrant) -> Callable[..., _FakeQdrant]:
    def _mk(_: QdrantConfig) -> _FakeQdrant:
        return fake

    return _mk


def _chunk(id_: str = "c1", content: str = "hello world") -> KnowledgeChunk:
    return KnowledgeChunk(id=id_, source_id="s1", ordinal=0, content=content, token_count=2)


def _hit(
    id_: str,
    score: float,
    *,
    source_id: str = "s1",
    content: str = "text",
    ordinal: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        score=score,
        payload={
            "chunk_id": id_,
            "source_id": source_id,
            "content": content,
            "ordinal": ordinal,
        },
    )


class TestQdrantLocalStore:
    async def test_missing_runtime_raises(self) -> None:
        store = QdrantLocalStore(config=QdrantConfig(), embedder=_FakeEmbedder())
        with pytest.raises(QdrantRuntimeNotAvailableError):
            await store.upsert((_chunk(),))

    async def test_upsert_batches_and_stores_hybrid_vectors(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(upsert_batch_size=2, dense_dim=64),
            embedder=_FakeEmbedder(dim=64),
            loader=_loader(fake),
        )
        chunks = tuple(_chunk(f"c{i}") for i in range(5))
        await store.upsert(chunks)
        assert [len(b) for b in fake.upserts] == [2, 2, 1]
        first_point = fake.upserts[0][0]
        assert first_point["payload"]["source_id"] == "s1"
        # Hybrid mode → the vector is a dict with `dense` + `sparse` names.
        vector = first_point["vector"]
        assert isinstance(vector, dict)
        assert "dense" in vector
        assert "sparse" in vector

    async def test_upsert_falls_back_to_dense_when_sparse_missing(self) -> None:
        fake = _FakeQdrant()
        embedder = _FakeEmbedder(sparse_available=False)
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=embedder,
            loader=_loader(fake),
        )
        await store.upsert((_chunk(),))
        vector = fake.upserts[0][0]["vector"]
        # No sparse embed available → only dense name emitted.
        assert isinstance(vector, dict)
        assert set(vector) == {"dense"}

    async def test_hybrid_search_calls_both_indexes_and_fuses(self) -> None:
        fake = _FakeQdrant(
            dense_hits=[
                _hit("c1", 0.9),
                _hit("c2", 0.7),
                _hit("c3", 0.6),
            ],
            sparse_hits=[
                _hit("c3", 0.95),  # sparse promotes c3
                _hit("c1", 0.8),
                _hit("c4", 0.5),
            ],
        )
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        hits = await store.search(RetrievalQuery(text="hybrid?", top_k=3))
        # Two searches happened: dense + sparse.
        vector_names = [c["vector"] for c in fake.search_calls]
        assert "dense" in vector_names
        assert "sparse" in vector_names
        # RRF fuses ranks; result set is <= top_k and contains promoted ids.
        ids = [h.chunk.id for h in hits]
        assert len(hits) <= 3
        assert set(ids) & {"c1", "c3"}

    async def test_dense_only_when_hybrid_disabled(self) -> None:
        fake = _FakeQdrant(dense_hits=[_hit("c1", 0.9)])
        store = QdrantLocalStore(
            config=QdrantConfig(hybrid=False),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        hits = await store.search(RetrievalQuery(text="dense only"))
        assert [c["vector"] for c in fake.search_calls] == [None]
        assert len(hits) == 1
        assert hits[0].chunk.id == "c1"

    async def test_search_degrades_when_sparse_index_missing(self) -> None:
        # Sparse-side search on a legacy collection may raise; adapter should
        # fall back to dense results without failing the query.
        class _Buggy(_FakeQdrant):
            def search(
                self,
                *,
                collection_name: str,
                query_vector: Any,
                limit: int,
                query_filter: Any,
            ) -> list[Any]:
                del collection_name, query_filter
                name = query_vector[0] if isinstance(query_vector, tuple) else None
                self.search_calls.append({"vector": name, "limit": limit})
                if name == "sparse":
                    msg = "collection has no sparse index"
                    raise RuntimeError(msg)
                return [_hit("c1", 0.9)]

        fake = _Buggy()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        hits = await store.search(RetrievalQuery(text="?"))
        assert len(hits) == 1
        assert hits[0].chunk.id == "c1"

    async def test_delete_by_source_uses_filter(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        await store.delete_by_source("s42")
        selector = fake.deletes[0]["points_selector"]
        assert selector["filter"]["must"][0]["match"]["value"] == "s42"

    async def test_close_calls_client_close(self) -> None:
        fake = _FakeQdrant()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        await store.delete_by_source("s1")
        await store.close()
        assert fake.closed

    async def test_list_sources_aggregates_scroll(self) -> None:
        fake = _FakeQdrant(
            scroll_pages=[
                [
                    SimpleNamespace(payload={"source_id": "s1"}),
                    SimpleNamespace(payload={"source_id": "s1"}),
                    SimpleNamespace(payload={"source_id": "s2"}),
                ],
                [
                    SimpleNamespace(payload={"source_id": "s1"}),
                    SimpleNamespace(payload={"source_id": "s3"}),
                ],
            ]
        )
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        summaries = await store.list_sources()
        by_id = {s.source_id: s.chunk_count for s in summaries}
        assert by_id == {"s1": 3, "s2": 1, "s3": 1}

    async def test_list_sources_returns_empty_on_scroll_failure(self) -> None:
        class _Buggy(_FakeQdrant):
            def scroll(self, **_kwargs: Any) -> tuple[list[Any], Any]:
                msg = "boom"
                raise RuntimeError(msg)

        fake = _Buggy()
        store = QdrantLocalStore(
            config=QdrantConfig(),
            embedder=_FakeEmbedder(),
            loader=_loader(fake),
        )
        assert await store.list_sources() == ()
