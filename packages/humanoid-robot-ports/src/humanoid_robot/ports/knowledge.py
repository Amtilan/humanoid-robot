"""Knowledge subsystem ports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeSource,
    RetrievalHit,
)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    top_k: int = Field(gt=0, le=100, default=8)
    dense_weight: float = Field(ge=0.0, le=1.0, default=0.7)
    sparse_weight: float = Field(ge=0.0, le=1.0, default=0.3)
    filters: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class VectorStorePort(Protocol):
    """Vector store — hybrid dense+sparse retrieval, keyed by chunk id."""

    async def upsert(self, chunks: tuple[KnowledgeChunk, ...]) -> None: ...

    async def delete_by_source(self, source_id: str) -> None: ...

    async def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]: ...

    async def close(self) -> None: ...


@runtime_checkable
class DocumentParserPort(Protocol):
    """Parses a raw file into a `KnowledgeSource` and its raw text."""

    def supported_kinds(self) -> tuple[str, ...]: ...

    async def parse(self, path: Path) -> tuple[KnowledgeSource, str]: ...


@runtime_checkable
class ChunkerPort(Protocol):
    """Splits raw text into `KnowledgeChunk`s."""

    def chunk(self, source: KnowledgeSource, text: str) -> AsyncIterator[KnowledgeChunk]: ...
