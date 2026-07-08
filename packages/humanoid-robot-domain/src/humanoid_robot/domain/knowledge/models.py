"""Knowledge domain — sources, chunks, retrieval hits, grounded answers.

Grounding rules (see ADR-0001, section on anti-hallucination):
    - `GroundedAnswer` MUST carry at least one `Citation` when the answer is
      not a policy-refusal.
    - Each `Citation.quote` MUST be verifiable against the referenced
      chunk's `content` (checked by a downstream `CitationVerifier`).
    - `RetrievalQualityVerdict.PASS` is a precondition for calling the LLM.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from humanoid_robot.domain.shared import Timestamp, utc_now


class KnowledgeSourceKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"
    CSV = "csv"
    IMAGE = "image"
    AUDIO = "audio"


class KnowledgeSource(BaseModel):
    """A logical document ingested into the knowledge base."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # content-addressed id (hash)
    uri: str  # original location (file:///..., s3://..., http://...)
    kind: KnowledgeSourceKind
    title: str
    content_hash: str
    ingested_at: Timestamp = Field(default_factory=utc_now)
    version: int = Field(ge=1, default=1)


class KnowledgeChunk(BaseModel):
    """A retrievable slice of a source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_id: str
    ordinal: int = Field(ge=0)
    content: str
    token_count: int = Field(ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)


class RetrievalHit(BaseModel):
    """One chunk returned by a retriever with its scores."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk: KnowledgeChunk
    dense_score: float
    sparse_score: float | None = None
    rerank_score: float | None = None

    @property
    def top_score(self) -> float:
        """The score to use for gating decisions."""
        return self.rerank_score if self.rerank_score is not None else self.dense_score


class RetrievalQualityVerdict(StrEnum):
    PASS = "pass"
    FAIL_LOW_SCORE = "fail_low_score"
    FAIL_LOW_COVERAGE = "fail_low_coverage"


class Citation(BaseModel):
    """A quote from a chunk supporting one claim in an answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    quote: str


class GroundingVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class GroundedAnswer(BaseModel):
    """LLM output constrained to what the retrieved chunks actually say."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    citations: tuple[Citation, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    grounding_verdict: GroundingVerdict = GroundingVerdict.SUPPORTED

    @model_validator(mode="after")
    def _require_citation_unless_refusal(self) -> Self:
        if self.grounding_verdict == GroundingVerdict.SUPPORTED and not self.citations:
            msg = "SUPPORTED answers must include at least one citation"
            raise ValueError(msg)
        return self
