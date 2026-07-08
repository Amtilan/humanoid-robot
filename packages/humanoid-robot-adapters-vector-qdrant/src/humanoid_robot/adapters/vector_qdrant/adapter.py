"""VectorStorePort via Qdrant in local (embedded) mode.

The adapter needs an `EmbeddingPort` supplied at construction; the
composition root binds them together so the entry-point factory only
needs to be told about the local storage location.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import (
    KnowledgeChunk,
    RetrievalHit,
)
from humanoid_robot.ports.ai import EmbeddingPort
from humanoid_robot.ports.knowledge import RetrievalQuery


class QdrantRuntimeNotAvailableError(RuntimeError):
    """Raised when the qdrant runtime dependency is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "qdrant-client is not installed. Install this adapter with its "
            "runtime extra: uv add 'humanoid-robot-adapters-vector-qdrant[runtime]'"
        )


class QdrantConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    local_path: str = "/var/lib/humanoid-robot/qdrant"
    collection: str = "knowledge"
    dense_dim: int = Field(default=1024, ge=64, le=8192)
    upsert_batch_size: int = Field(default=64, ge=1, le=1024)


@dataclass(slots=True)
class QdrantLocalStore:
    """VectorStorePort backed by Qdrant local mode."""

    config: QdrantConfig
    embedder: EmbeddingPort
    _loader: Any = None  # Optional (config -> QdrantClient) for tests
    _client: Any = field(default=None, init=False)

    def __init__(
        self,
        config: QdrantConfig,
        embedder: EmbeddingPort,
        *,
        loader: Any = None,
    ) -> None:
        self.config = config
        self.embedder = embedder
        self._loader = loader
        self._client = None

    async def upsert(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        if not chunks:
            return
        client = self._ensure_client()
        batch = self.config.upsert_batch_size
        for start in range(0, len(chunks), batch):
            slice_ = chunks[start : start + batch]
            dense = await self.embedder.embed_dense(tuple(c.content for c in slice_))
            points: list[dict[str, object]] = []
            for chunk, vec in zip(slice_, dense, strict=False):
                payload: dict[str, object] = {
                    "chunk_id": chunk.id,
                    "source_id": chunk.source_id,
                    "content": chunk.content,
                    "ordinal": chunk.ordinal,
                }
                payload.update(chunk.metadata)
                points.append({"id": chunk.id, "vector": list(vec), "payload": payload})
            await self._run(
                lambda p=points: client.upsert(
                    collection_name=self.config.collection,
                    points=p,
                )
            )

    async def delete_by_source(self, source_id: str) -> None:
        client = self._ensure_client()
        await self._run(
            lambda: client.delete(
                collection_name=self.config.collection,
                points_selector={
                    "filter": {"must": [{"key": "source_id", "match": {"value": source_id}}]}
                },
            )
        )

    async def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        client = self._ensure_client()
        (dense_vec,) = await self.embedder.embed_dense((query.text,))
        raw_hits = await self._run(
            lambda: client.search(
                collection_name=self.config.collection,
                query_vector=list(dense_vec),
                limit=query.top_k,
                query_filter=_build_filter(query.filters) or None,
            )
        )
        hits: list[RetrievalHit] = []
        for h in raw_hits:
            payload = getattr(h, "payload", None) or {}
            chunk = KnowledgeChunk(
                id=str(payload.get("chunk_id") or getattr(h, "id", "")),
                source_id=str(payload.get("source_id", "")),
                ordinal=int(payload.get("ordinal", 0)),
                content=str(payload.get("content", "")),
                token_count=len(str(payload.get("content", ""))) // 4,
                metadata={
                    str(k): str(v)
                    for k, v in payload.items()
                    if k not in {"chunk_id", "source_id", "content", "ordinal"}
                },
            )
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    dense_score=float(getattr(h, "score", 0.0)),
                )
            )
        return tuple(hits)

    async def close(self) -> None:
        if self._client is None:
            return
        # QdrantClient.close is synchronous.
        await self._run(self._client.close)
        self._client = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._loader is not None:
            self._client = self._loader(self.config)
            return self._client
        try:
            qdrant = importlib.import_module("qdrant_client")
        except ImportError as exc:
            raise QdrantRuntimeNotAvailableError from exc
        self._client = qdrant.QdrantClient(path=self.config.local_path)
        _ensure_collection(self._client, self.config)
        return self._client

    async def _run(self, fn: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn)


def _ensure_collection(client: Any, config: QdrantConfig) -> None:
    """Best-effort: create the collection if it does not yet exist."""
    try:
        client.get_collection(config.collection)
    except Exception:  # noqa: BLE001
        from qdrant_client.http import models  # noqa: PLC0415

        client.recreate_collection(
            collection_name=config.collection,
            vectors_config=models.VectorParams(
                size=config.dense_dim, distance=models.Distance.COSINE
            ),
        )


def _build_filter(filters: dict[str, str]) -> dict[str, Any] | None:
    if not filters:
        return None
    return {"must": [{"key": key, "match": {"value": value}} for key, value in filters.items()]}


def build_qdrant_local(
    *,
    embedder: EmbeddingPort,
    **kwargs: object,
) -> QdrantLocalStore:
    """Entry-point factory. `embedder` is injected by the composition root."""
    return QdrantLocalStore(config=QdrantConfig.model_validate(kwargs), embedder=embedder)
