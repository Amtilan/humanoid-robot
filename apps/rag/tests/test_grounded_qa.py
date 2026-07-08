"""GroundedQAOrchestrator tests with all-fake ports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from humanoid_robot.domain.knowledge import (
    KnowledgeChunk,
    RetrievalHit,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.ports.ai import LlmRequest, LlmResponse
from humanoid_robot.ports.knowledge import RetrievalQuery
from humanoid_robot.rag import (
    GroundedQAConfig,
    GroundedQAOrchestrator,
    GroundingJudgeVerdict,
    RetrievalQualityVerdict,
)


def _chunk(id_: str, content: str) -> KnowledgeChunk:
    return KnowledgeChunk(id=id_, source_id="s1", ordinal=0, content=content, token_count=8)


def _hit(id_: str, content: str, score: float) -> RetrievalHit:
    return RetrievalHit(chunk=_chunk(id_, content), dense_score=score)


@dataclass(slots=True)
class _FakeStore:
    scripted: tuple[RetrievalHit, ...]

    async def upsert(self, _chunks: tuple[KnowledgeChunk, ...]) -> None:
        return

    async def delete_by_source(self, _source_id: str) -> None:
        return

    async def search(self, _query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        return self.scripted

    async def close(self) -> None:
        return


@dataclass(slots=True)
class _FakeReranker:
    scripted: dict[str, float]

    async def rerank(self, _query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        return tuple(self.scripted.get(p, 0.0) for p in passages)


@dataclass(slots=True)
class _ScriptedLlm:
    """Returns pre-scripted responses in order, one per `generate` call."""

    replies: list[str]
    _index: int = 0
    calls: list[LlmRequest] = field(default_factory=list)

    async def generate(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        text = self.replies[min(self._index, len(self.replies) - 1)]
        self._index += 1
        return LlmResponse(
            text=text,
            prompt_tokens=1,
            completion_tokens=len(text.split()),
            finish_reason="stop",
        )

    def stream(self, _r: LlmRequest) -> AsyncIterator[str]:  # pragma: no cover
        raise NotImplementedError


class TestGroundedQAOrchestrator:
    async def test_pass_through_supported_answer(self) -> None:
        hit1 = _hit("c1", "Робот работает полностью офлайн.", 0.8)
        hit2 = _hit("c2", "Второй релевантный кусок текста для покрытия.", 0.7)
        answer_json = (
            '{"answer": "Работает офлайн.", '
            '"citations": [{"chunk_id": "c1", "quote": "полностью офлайн"}], '
            '"confidence": 0.9, "grounding_verdict": "supported"}'
        )
        judge_json = '{"supported": "yes"}'
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=(hit1, hit2)),
            reranker=_FakeReranker(scripted={hit1.chunk.content: 0.9, hit2.chunk.content: 0.7}),
            llm=_ScriptedLlm(replies=[answer_json, judge_json]),
            config=GroundedQAConfig(
                min_top1_rerank_score=0.3,
                min_chunk_coverage=1,
            ),
        )
        result = await orch.answer("Работает ли робот офлайн?", Language.RU)
        assert result.retrieval_verdict == RetrievalQualityVerdict.PASS
        assert result.grounding_verdict == GroundingJudgeVerdict.SUPPORTED
        assert result.answer is not None
        assert result.answer.answer == "Работает офлайн."

    async def test_empty_retrieval_gets_no_answer_reply(self) -> None:
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=()),
            reranker=_FakeReranker(scripted={}),
            llm=_ScriptedLlm(replies=[]),
        )
        result = await orch.answer("что?", Language.RU)
        assert result.retrieval_verdict == RetrievalQualityVerdict.FAIL_LOW_COVERAGE
        assert result.answer is None
        assert result.fallback_text is not None

    async def test_low_score_triggers_gate_fail(self) -> None:
        hit = _hit("c1", "нерелевантно", 0.1)
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=(hit,)),
            reranker=_FakeReranker(scripted={hit.chunk.content: 0.1}),
            llm=_ScriptedLlm(replies=[]),
            config=GroundedQAConfig(min_top1_rerank_score=0.5, min_chunk_coverage=1),
        )
        result = await orch.answer("вопрос", Language.RU)
        assert result.retrieval_verdict == RetrievalQualityVerdict.FAIL_LOW_SCORE

    async def test_citation_verifier_rejects_hallucinated_chunk_id(self) -> None:
        hit = _hit("c1", "исходный текст ответа", 0.9)
        bad_answer = (
            '{"answer": "выдумка", "citations": ['
            '{"chunk_id": "c999", "quote": "не существует"}], '
            '"confidence": 0.9, "grounding_verdict": "supported"}'
        )
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=(hit,)),
            reranker=_FakeReranker(scripted={hit.chunk.content: 0.9}),
            llm=_ScriptedLlm(replies=[bad_answer, bad_answer]),
            config=GroundedQAConfig(
                min_top1_rerank_score=0.3,
                min_chunk_coverage=1,
                max_retries_on_citation_fail=1,
            ),
        )
        result = await orch.answer("вопрос", Language.RU)
        assert result.citations_verified is False
        assert result.rejection_reason == "citation_verify_failed"
        assert result.answer is None

    async def test_grounding_judge_rejection(self) -> None:
        hit = _hit("c1", "источник", 0.9)
        answer_json = (
            '{"answer": "текст ответа", '
            '"citations": [{"chunk_id": "c1", "quote": "источник"}], '
            '"confidence": 0.9, "grounding_verdict": "supported"}'
        )
        judge_json = '{"supported": "no"}'
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=(hit,)),
            reranker=_FakeReranker(scripted={hit.chunk.content: 0.9}),
            llm=_ScriptedLlm(replies=[answer_json, judge_json]),
            config=GroundedQAConfig(min_top1_rerank_score=0.3, min_chunk_coverage=1),
        )
        result = await orch.answer("вопрос", Language.RU)
        assert result.grounding_verdict == GroundingJudgeVerdict.UNSUPPORTED
        assert result.answer is None
