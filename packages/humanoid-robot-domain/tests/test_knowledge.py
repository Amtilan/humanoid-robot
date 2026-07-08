"""Knowledge domain tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from humanoid_robot.domain.knowledge import (
    Citation,
    GroundedAnswer,
    GroundingVerdict,
    KnowledgeChunk,
    RetrievalHit,
)


def _chunk(id_: str = "c1", content: str = "The robot is offline-first.") -> KnowledgeChunk:
    return KnowledgeChunk(id=id_, source_id="s1", ordinal=0, content=content, token_count=6)


class TestRetrievalHit:
    def test_top_score_prefers_rerank(self) -> None:
        hit = RetrievalHit(chunk=_chunk(), dense_score=0.5, rerank_score=0.9)
        assert hit.top_score == pytest.approx(0.9)

    def test_top_score_falls_back_to_dense(self) -> None:
        hit = RetrievalHit(chunk=_chunk(), dense_score=0.7)
        assert hit.top_score == pytest.approx(0.7)


class TestGroundedAnswer:
    def test_supported_requires_citation(self) -> None:
        with pytest.raises(ValidationError):
            GroundedAnswer(
                answer="Yes",
                citations=(),
                confidence=0.9,
                grounding_verdict=GroundingVerdict.SUPPORTED,
            )

    def test_unsupported_allows_no_citation(self) -> None:
        ans = GroundedAnswer(
            answer="I could not find information about that.",
            citations=(),
            confidence=1.0,
            grounding_verdict=GroundingVerdict.UNSUPPORTED,
        )
        assert ans.citations == ()

    def test_supported_with_citations_ok(self) -> None:
        ans = GroundedAnswer(
            answer="The platform runs offline.",
            citations=(Citation(chunk_id="c1", quote="offline-first"),),
            confidence=0.85,
        )
        assert ans.grounding_verdict == GroundingVerdict.SUPPORTED
