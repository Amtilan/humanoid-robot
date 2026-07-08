"""VectorStorePort via Qdrant in local (embedded) mode.

Supports hybrid retrieval: every point carries a **dense** vector (BGE-M3
1024-d) and a **sparse** vector (BGE-M3 lexical weights).  `search` runs
both retrievals and fuses them via Reciprocal Rank Fusion (RRF).  Falls
back to dense-only when the embedder does not implement `embed_sparse`.

The adapter needs an `EmbeddingPort` supplied at construction; the
composition root binds them together so the entry-point factory only
needs to be told about the local storage location.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import KnowledgeChunk, RetrievalHit
from humanoid_robot.ports.ai import EmbeddingPort
from humanoid_robot.ports.knowledge import RetrievalQuery

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"
_RRF_K = 60  # per Cormack, Clarke, and Buettcher (2009) — standard RRF constant


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
    hybrid: bool = True
    sparse_prefetch_multiplier: int = Field(default=4, ge=1, le=20)


@dataclass(slots=True)
class QdrantLocalStore:
    """VectorStorePort backed by Qdrant local mode with optional hybrid search."""

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
            sparse = await self._safe_embed_sparse(tuple(c.content for c in slice_))
            points = self._build_points(slice_, dense, sparse)

            def _do_upsert(p: list[dict[str, object]] = points) -> None:
                client.upsert(collection_name=self.config.collection, points=p)

            await self._run(_do_upsert)

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
        (dense_vec,) = await self.embedder.embed_dense((query.text,))
        sparse_vecs = await self._safe_embed_sparse((query.text,))
        sparse_map = sparse_vecs[0] if sparse_vecs else None

        client = self._ensure_client()
        payload_filter = _build_filter(query.filters) or None

        dense_hits = await self._run(
            lambda: client.search(
                collection_name=self.config.collection,
                query_vector=(_DENSE_VECTOR_NAME, list(dense_vec))
                if self.config.hybrid
                else list(dense_vec),
                limit=query.top_k,
                query_filter=payload_filter,
            )
        )

        if not (self.config.hybrid and sparse_map):
            return tuple(_to_hit(h, sparse_score=None) for h in dense_hits)

        prefetch = max(query.top_k * self.config.sparse_prefetch_multiplier, query.top_k)
        try:
            sparse_hits = await self._run(
                lambda: client.search(
                    collection_name=self.config.collection,
                    query_vector=(_SPARSE_VECTOR_NAME, _to_sparse_query(sparse_map)),
                    limit=prefetch,
                    query_filter=payload_filter,
                )
            )
        except Exception:  # noqa: BLE001
            # Sparse index may be absent (older collection); degrade gracefully.
            return tuple(_to_hit(h, sparse_score=None) for h in dense_hits)

        fused = _rrf_fuse(
            dense_hits,
            sparse_hits,
            top_k=query.top_k,
            dense_weight=query.dense_weight,
            sparse_weight=query.sparse_weight,
        )
        return tuple(fused)

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

    async def _run(self, fn: Callable[[], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn)

    async def _safe_embed_sparse(
        self, texts: tuple[str, ...]
    ) -> tuple[dict[int, float], ...] | None:
        if not self.config.hybrid:
            return None
        embed_sparse = getattr(self.embedder, "embed_sparse", None)
        if embed_sparse is None:
            return None
        try:
            result = await embed_sparse(texts)
        except NotImplementedError:
            return None
        return tuple(result)

    def _build_points(
        self,
        chunks: tuple[KnowledgeChunk, ...],
        dense: tuple[tuple[float, ...], ...],
        sparse: tuple[dict[int, float], ...] | None,
    ) -> list[dict[str, object]]:
        points: list[dict[str, object]] = []
        for i, (chunk, vec) in enumerate(zip(chunks, dense, strict=False)):
            payload: dict[str, object] = {
                "chunk_id": chunk.id,
                "source_id": chunk.source_id,
                "content": chunk.content,
                "ordinal": chunk.ordinal,
            }
            payload.update(chunk.metadata)
            if self.config.hybrid and sparse is not None:
                vector: object = {
                    _DENSE_VECTOR_NAME: list(vec),
                    _SPARSE_VECTOR_NAME: _to_sparse_vector(sparse[i]),
                }
            elif self.config.hybrid:
                vector = {_DENSE_VECTOR_NAME: list(vec)}
            else:
                vector = list(vec)
            points.append({"id": chunk.id, "vector": vector, "payload": payload})
        return points


def _ensure_collection(client: Any, config: QdrantConfig) -> None:
    """Best-effort: create the collection if it does not yet exist."""
    try:
        client.get_collection(config.collection)
    except Exception:  # noqa: BLE001
        from qdrant_client.http import models  # noqa: PLC0415

        if config.hybrid:
            client.recreate_collection(
                collection_name=config.collection,
                vectors_config={
                    _DENSE_VECTOR_NAME: models.VectorParams(
                        size=config.dense_dim, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={_SPARSE_VECTOR_NAME: models.SparseVectorParams()},
            )
        else:
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


def _to_sparse_vector(weights: dict[int, float]) -> Any:
    """Convert the port's sparse map to Qdrant's SparseVector, if available."""
    try:
        models = importlib.import_module("qdrant_client.http.models")
    except ImportError:
        # Fall back to a plain dict — the local qdrant client accepts either.
        return {"indices": list(weights), "values": [float(v) for v in weights.values()]}
    return models.SparseVector(
        indices=list(weights),
        values=[float(v) for v in weights.values()],
    )


def _to_sparse_query(weights: dict[int, float]) -> Any:
    """Same as `_to_sparse_vector` — kept as its own helper for future tuning."""
    return _to_sparse_vector(weights)


def _to_hit(raw: Any, *, sparse_score: float | None) -> RetrievalHit:
    payload = getattr(raw, "payload", None) or {}
    content = str(payload.get("content", ""))
    chunk = KnowledgeChunk(
        id=str(payload.get("chunk_id") or getattr(raw, "id", "")),
        source_id=str(payload.get("source_id", "")),
        ordinal=int(payload.get("ordinal", 0)),
        content=content,
        token_count=len(content) // 4,
        metadata={
            str(k): str(v)
            for k, v in payload.items()
            if k not in {"chunk_id", "source_id", "content", "ordinal"}
        },
    )
    return RetrievalHit(
        chunk=chunk,
        dense_score=float(getattr(raw, "score", 0.0)),
        sparse_score=sparse_score,
    )


def _rrf_fuse(
    dense_hits: list[Any],
    sparse_hits: list[Any],
    *,
    top_k: int,
    dense_weight: float,
    sparse_weight: float,
) -> list[RetrievalHit]:
    """Reciprocal Rank Fusion — score = w_d/(k+r_d) + w_s/(k+r_s)."""
    combined: dict[str, dict[str, Any]] = {}
    for rank, raw in enumerate(dense_hits, start=1):
        key = _hit_key(raw)
        entry = combined.setdefault(key, {"raw": raw, "dense_rank": None, "sparse_rank": None})
        entry["raw"] = raw
        entry["dense_rank"] = rank
        entry["dense_score"] = float(getattr(raw, "score", 0.0))
    for rank, raw in enumerate(sparse_hits, start=1):
        key = _hit_key(raw)
        entry = combined.setdefault(key, {"raw": raw, "dense_rank": None, "sparse_rank": None})
        entry["sparse_rank"] = rank
        entry["sparse_score"] = float(getattr(raw, "score", 0.0))
        # Prefer the payload-carrying raw hit when both sides return it.
        if entry.get("raw") is None:
            entry["raw"] = raw

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in combined.values():
        dense_rank = entry.get("dense_rank")
        sparse_rank = entry.get("sparse_rank")
        score = 0.0
        if dense_rank is not None:
            score += dense_weight / (_RRF_K + dense_rank)
        if sparse_rank is not None:
            score += sparse_weight / (_RRF_K + sparse_rank)
        entry["fused"] = score
        scored.append((score, entry))

    scored.sort(key=lambda p: p[0], reverse=True)
    fused: list[RetrievalHit] = []
    for _, entry in scored[:top_k]:
        raw = entry["raw"]
        sparse_score = entry.get("sparse_score")
        hit = _to_hit(raw, sparse_score=sparse_score)
        # Override dense_score with what dense retrieval actually reported
        # (RRF fusion aside), so upstream gates keep operating on comparable
        # per-modality signals.
        dense_score = entry.get("dense_score")
        if dense_score is not None:
            hit = RetrievalHit(
                chunk=hit.chunk,
                dense_score=float(dense_score),
                sparse_score=sparse_score,
                rerank_score=None,
            )
        fused.append(hit)
    return fused


def _hit_key(raw: Any) -> str:
    """Stable key for pairing a hit across dense and sparse retrievals."""
    payload = getattr(raw, "payload", None) or {}
    key = payload.get("chunk_id") or getattr(raw, "id", None)
    return str(key)


def build_qdrant_local(
    *,
    embedder: EmbeddingPort,
    **kwargs: object,
) -> QdrantLocalStore:
    """Entry-point factory. `embedder` is injected by the composition root."""
    return QdrantLocalStore(config=QdrantConfig.model_validate(kwargs), embedder=embedder)
