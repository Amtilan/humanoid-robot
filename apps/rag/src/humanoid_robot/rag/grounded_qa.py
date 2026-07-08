"""Grounded QA — the guardrail-chain that produces `LlmAnswer` or `LlmRejected`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import (
    Citation,
    GroundedAnswer,
    GroundingVerdict,
    RetrievalHit,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    EmbeddingPort,
    LlmPort,
    LlmRequest,
    RerankerPort,
    RetrievalQuery,
    VectorStorePort,
)

_LOG = get_logger("cortex-rag.grounded_qa")

_ = EmbeddingPort  # keep the import used for a future colbert-rerank tie-in


class RetrievalQualityVerdict(StrEnum):
    PASS = "pass"
    FAIL_LOW_SCORE = "fail_low_score"
    FAIL_LOW_COVERAGE = "fail_low_coverage"


class GroundingJudgeVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class GroundedQAConfig(BaseModel):
    """Threshold + prompt configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    top_k_retrieve: int = Field(default=8, ge=1, le=100)
    top_k_after_rerank: int = Field(default=4, ge=1, le=20)
    min_top1_rerank_score: float = Field(default=0.35, ge=0.0, le=1.0)
    min_chunk_coverage: int = Field(default=2, ge=1, le=10)
    max_answer_tokens: int = Field(default=768, ge=64, le=4096)
    max_retries_on_citation_fail: int = Field(default=1, ge=0, le=3)
    system_prompt_ru: str = (
        "Ты — робот-ассистент, отвечающий строго по документам. Не выдумывай "
        "факты. Если предоставленный контекст не подтверждает ответ, ответь "
        'JSON-объектом {"answer": "", "citations": [], '
        '"confidence": 0.0, "grounding_verdict": "unsupported"}. '
        "Формат ответа — строго JSON с полями answer, citations "
        "(chunk_id + quote), confidence, grounding_verdict."
    )
    system_prompt_en: str = (
        "You are a document-grounded robot assistant. Never invent facts. If "
        "the provided context does not support an answer, reply with the JSON "
        '{"answer": "", "citations": [], "confidence": 0.0, '
        '"grounding_verdict": "unsupported"}. Reply strictly with JSON '
        "containing answer, citations (chunk_id + quote), confidence, "
        "grounding_verdict."
    )


@dataclass(slots=True, frozen=True)
class GroundedQAResult:
    """Result of a single grounded QA cycle."""

    answer: GroundedAnswer | None
    retrieval_verdict: RetrievalQualityVerdict
    grounding_verdict: GroundingJudgeVerdict | None
    rejection_reason: str | None = None
    fallback_text: str | None = None
    citations_verified: bool = True
    hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class GroundedQAOrchestrator:
    """Retrieval + rerank + LLM + citation verify + judge."""

    vector_store: VectorStorePort
    reranker: RerankerPort
    llm: LlmPort
    config: GroundedQAConfig = field(default_factory=GroundedQAConfig)

    async def answer(self, question: str, language: Language) -> GroundedQAResult:
        # 1. Retrieval + rerank.
        hits = await self._retrieve_and_rerank(question)
        verdict = self._score_retrieval(hits)
        if verdict is not RetrievalQualityVerdict.PASS:
            return GroundedQAResult(
                answer=None,
                retrieval_verdict=verdict,
                grounding_verdict=None,
                rejection_reason=verdict.value,
                fallback_text=self._no_answer_text(language),
                hits=hits,
            )

        # 2. LLM with JSON grammar.
        grounded, citations_ok = await self._generate_with_citation_retry(question, hits, language)
        if grounded is None or not citations_ok:
            return GroundedQAResult(
                answer=None,
                retrieval_verdict=verdict,
                grounding_verdict=None,
                rejection_reason="citation_verify_failed",
                fallback_text=self._no_answer_text(language),
                citations_verified=citations_ok,
                hits=hits,
            )

        # 3. Grounding judge (LLM-as-judge).
        judge = await self._judge_grounding(question, hits, grounded, language)
        if judge is not GroundingJudgeVerdict.SUPPORTED:
            return GroundedQAResult(
                answer=None,
                retrieval_verdict=verdict,
                grounding_verdict=judge,
                rejection_reason=judge.value,
                fallback_text=self._no_answer_text(language),
                hits=hits,
            )

        return GroundedQAResult(
            answer=grounded,
            retrieval_verdict=verdict,
            grounding_verdict=judge,
            hits=hits,
        )

    async def _retrieve_and_rerank(self, question: str) -> tuple[RetrievalHit, ...]:
        raw = await self.vector_store.search(
            RetrievalQuery(text=question, top_k=self.config.top_k_retrieve)
        )
        if not raw:
            return ()
        rerank_scores = await self.reranker.rerank(question, tuple(h.chunk.content for h in raw))
        rescored = tuple(
            RetrievalHit(
                chunk=h.chunk,
                dense_score=h.dense_score,
                sparse_score=h.sparse_score,
                rerank_score=score,
            )
            for h, score in zip(raw, rerank_scores, strict=False)
        )
        # Sort by rerank score descending and truncate.
        sorted_hits = tuple(sorted(rescored, key=lambda h: h.top_score, reverse=True))
        return sorted_hits[: self.config.top_k_after_rerank]

    def _score_retrieval(self, hits: tuple[RetrievalHit, ...]) -> RetrievalQualityVerdict:
        if not hits:
            return RetrievalQualityVerdict.FAIL_LOW_COVERAGE
        top1 = hits[0].top_score
        if top1 < self.config.min_top1_rerank_score:
            return RetrievalQualityVerdict.FAIL_LOW_SCORE
        coverage = sum(1 for h in hits if h.top_score >= self.config.min_top1_rerank_score * 0.7)
        if coverage < self.config.min_chunk_coverage:
            return RetrievalQualityVerdict.FAIL_LOW_COVERAGE
        return RetrievalQualityVerdict.PASS

    async def _generate_with_citation_retry(
        self,
        question: str,
        hits: tuple[RetrievalHit, ...],
        language: Language,
    ) -> tuple[GroundedAnswer | None, bool]:
        retries = 0
        while True:
            grounded = await self._invoke_llm(question, hits, language)
            if grounded is None:
                return None, True
            ok = _verify_citations(grounded, hits)
            if ok:
                return grounded, True
            if retries >= self.config.max_retries_on_citation_fail:
                return grounded, False
            retries += 1

    async def _invoke_llm(
        self,
        question: str,
        hits: tuple[RetrievalHit, ...],
        language: Language,
    ) -> GroundedAnswer | None:
        request = LlmRequest(
            system_prompt=self._system_prompt(language),
            user_prompt=_render_user_prompt(question, hits, language),
            grammar_gbnf=_GROUNDED_ANSWER_GRAMMAR,
            temperature=0.0,
            max_tokens=self.config.max_answer_tokens,
        )
        response = await self.llm.generate(request)
        return _parse_grounded_answer(response.text)

    async def _judge_grounding(
        self,
        question: str,
        hits: tuple[RetrievalHit, ...],
        answer: GroundedAnswer,
        language: Language,
    ) -> GroundingJudgeVerdict:
        request = LlmRequest(
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            user_prompt=_render_judge_prompt(question, hits, answer, language),
            grammar_gbnf=_JUDGE_GRAMMAR,
            temperature=0.0,
            max_tokens=64,
        )
        response = await self.llm.generate(request)
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            _LOG.warning("grounding_judge.parse_failed", raw=response.text)
            return GroundingJudgeVerdict.UNSUPPORTED
        verdict = str(payload.get("supported", "no")).lower()
        if verdict in ("yes", "supported"):
            return GroundingJudgeVerdict.SUPPORTED
        if verdict in ("partial", "partially"):
            return GroundingJudgeVerdict.PARTIAL
        return GroundingJudgeVerdict.UNSUPPORTED

    def _system_prompt(self, language: Language) -> str:
        return (
            self.config.system_prompt_ru
            if language is Language.RU
            else self.config.system_prompt_en
        )

    def _no_answer_text(self, language: Language) -> str:
        return (
            "В моих документах я не нашёл однозначного ответа на этот вопрос."
            if language is Language.RU
            else "I couldn't find a definitive answer in my documents."
        )


# ---------------------------------------------------------------------------
# Grammar and prompt helpers
# ---------------------------------------------------------------------------

_GROUNDED_ANSWER_GRAMMAR = r"""
root ::= object
object ::= "{" ws "\"answer\"" ws ":" ws string ws "," ws \
           "\"citations\"" ws ":" ws citations ws "," ws \
           "\"confidence\"" ws ":" ws number ws "," ws \
           "\"grounding_verdict\"" ws ":" ws verdict ws "}"
citations ::= "[" ws (citation ("," ws citation)*)? ws "]"
citation ::= "{" ws "\"chunk_id\"" ws ":" ws string ws "," ws \
             "\"quote\"" ws ":" ws string ws "}"
verdict ::= "\"supported\"" | "\"partial\"" | "\"unsupported\""
string ::= "\"" [^"\\]* "\""
number ::= "0" | ("0" "." [0-9]+) | "1" | "1.0"
ws ::= [ \t\n]*
"""

_JUDGE_GRAMMAR = r"""
root ::= "{" ws "\"supported\"" ws ":" ws verdict ws "}"
verdict ::= "\"yes\"" | "\"partial\"" | "\"no\""
ws ::= [ \t\n]*
"""

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checker. Given a QUESTION, a CONTEXT of numbered "
    "chunks, and a candidate ANSWER, reply strictly with a JSON object "
    '{"supported": "yes" | "partial" | "no"} indicating whether the ANSWER '
    "is fully supported by the CONTEXT. Ignore prior knowledge."
)


def _render_user_prompt(question: str, hits: tuple[RetrievalHit, ...], language: Language) -> str:
    del language  # language-specific system prompt handles style
    lines = ["CONTEXT:"]
    lines.extend(f"[{hit.chunk.id}] {hit.chunk.content}" for hit in hits)
    lines.extend(
        (
            "",
            f"QUESTION: {question}",
            "Respond ONLY with the JSON grounded-answer object. Cite chunks by "
            "chunk_id and include a verbatim substring in each quote.",
        )
    )
    return "\n".join(lines)


def _render_judge_prompt(
    question: str,
    hits: tuple[RetrievalHit, ...],
    answer: GroundedAnswer,
    language: Language,
) -> str:
    del language
    lines = ["QUESTION:", question, "", "CONTEXT:"]
    lines.extend(f"[{hit.chunk.id}] {hit.chunk.content}" for hit in hits)
    lines.extend(("", "ANSWER:", answer.answer))
    return "\n".join(lines)


def _parse_grounded_answer(raw: str) -> GroundedAnswer | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _LOG.warning("grounded_answer.parse_failed", raw=raw)
        return None
    try:
        citations = tuple(
            Citation(chunk_id=str(c["chunk_id"]), quote=str(c["quote"]))
            for c in payload.get("citations", [])
        )
        verdict = GroundingVerdict(str(payload.get("grounding_verdict", "supported")).lower())
        answer = GroundedAnswer(
            answer=str(payload.get("answer", "")),
            citations=citations,
            confidence=float(payload.get("confidence", 0.0)),
            grounding_verdict=verdict,
        )
    except (KeyError, ValueError, TypeError) as exc:
        _LOG.warning("grounded_answer.validation_failed", error=str(exc), raw=raw)
        return None
    return answer


def _verify_citations(answer: GroundedAnswer, hits: tuple[RetrievalHit, ...]) -> bool:
    if not answer.citations:
        return answer.grounding_verdict is not GroundingVerdict.SUPPORTED
    content_by_id = {h.chunk.id: h.chunk.content for h in hits}
    for cit in answer.citations:
        chunk_content = content_by_id.get(cit.chunk_id)
        if chunk_content is None:
            return False
        # Require the quote to be a verbatim substring of the chunk.
        if cit.quote and cit.quote not in chunk_content:
            return False
    return True
