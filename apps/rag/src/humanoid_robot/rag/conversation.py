"""Conversational orchestrator — a RAG-augmented chat that always answers.

Unlike `GroundedQAOrchestrator` (strict, document-only, rejects anything the
knowledge base can't support), this produces a natural conversational reply:
it best-effort retrieves relevant knowledge-base context and hands it to the
LLM as *optional* grounding, but the model is free to just chat from its own
knowledge when nothing relevant is retrieved. Retrieval failures (empty KB,
no vector store) degrade gracefully to pure chat.

It returns the same `GroundedQAResult` shape as the grounded orchestrator so
`RagRunner` can publish `llm.answer` unchanged. Chat replies carry no verbatim
citations, so they use the `PARTIAL` grounding verdict (which — unlike
`SUPPORTED` — does not require a citation).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import (
    GroundedAnswer,
    GroundingVerdict,
    RetrievalHit,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    LlmPort,
    LlmRequest,
    RerankerPort,
    RetrievalQuery,
    VectorStorePort,
)
from humanoid_robot.rag.grounded_qa import (
    GroundedQAResult,
    GroundingJudgeVerdict,
    RetrievalQualityVerdict,
)

_LOG = get_logger("cortex-rag.conversation")


class ConversationConfig(BaseModel):
    """Persona + retrieval tuning for the conversational path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Skip retrieval entirely (pure chat) when there is no knowledge base yet —
    # the embedder/reranker are CPU-bound here and add seconds per turn while
    # always degrading to chat anyway. Flip to true once documents are ingested.
    retrieve: bool = Field(default=True)
    top_k_retrieve: int = Field(default=6, ge=1, le=50)
    top_k_context: int = Field(default=3, ge=0, le=10)
    min_context_score: float = Field(default=0.30, ge=0.0, le=1.0)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=32, le=4096)
    system_prompt_ru: str = (
        "Тебя зовут Слуга. Ты — дружелюбный человекоподобный робот-помощник "
        "(Unitree G1). Ты живой, стоишь на ногах и общаешься голосом. К тебе "
        "обращаются по имени — Слуга. Это разговор вслух: отвечай ОЧЕНЬ коротко "
        "и естественно, не больше двух-трёх коротких предложений, без списков и "
        "вступлений. Всегда заканчивай ответ полным предложением — никогда не "
        "обрывай мысль на середине. Если ниже дан релевантный контекст из базы "
        "знаний, используй его; если нет — просто поболтай, опираясь на свои "
        "знания. Не выдумывай конкретные факты о документах, которых тебе не "
        "давали."
    )
    system_prompt_en: str = (
        "Your name is Sluga (Слуга). You are a friendly humanoid helper robot "
        "(Unitree G1). You are alive, standing on your feet and talking out "
        "loud. Answer briefly, naturally and conversationally in English — this "
        "is spoken, so keep it to 1–3 sentences. If relevant knowledge-base "
        "context is given below, use it; if not, just chat from your own "
        "knowledge. Do not invent specific facts about documents you were not "
        "given."
    )


# Rolling dialogue memory: enough context to feel like a conversation without
# inflating prefill (llama.cpp caches the common prefix, so the cost of old
# turns is paid once).
_HISTORY_MAX_TURNS = 6

_SENTENCE_END_CHARS = ".!?…"
_CLOSING_CHARS = "»\")]'"


def trim_incomplete_tail(text: str) -> str:
    """Cut a max_tokens-truncated answer back to its last finished sentence.

    Spoken aloud, a mid-sentence cut sounds like the robot breaking off; the
    chat shows the same trimmed text so voice and screen stay consistent.
    Text with no finished sentence at all is returned as-is — half an answer
    beats silence.
    """
    t = text.strip()
    if not t:
        return t
    core = t.rstrip(_CLOSING_CHARS)
    if core and core[-1] in _SENTENCE_END_CHARS:
        return t
    for i in range(len(core) - 1, -1, -1):
        if core[i] in _SENTENCE_END_CHARS:
            end = i + 1
            while end < len(t) and t[end] in _CLOSING_CHARS:
                end += 1
            return t[:end].strip()
    return t


@dataclass(slots=True)
class ConversationOrchestrator:
    """RAG-augmented conversational reply generator."""

    vector_store: VectorStorePort
    reranker: RerankerPort
    llm: LlmPort
    config: ConversationConfig = field(default_factory=ConversationConfig)
    # One physical robot, one conversation: a single rolling history of
    # (role, content) turns shared across sessions (voice + dashboard).
    _history: list[tuple[str, str]] = field(default_factory=list)

    def _remember(self, question: str, answer: str) -> None:
        self._history.append(("user", question))
        self._history.append(("assistant", answer))
        del self._history[: -_HISTORY_MAX_TURNS * 2]

    async def stream_answer(self, question: str, language: Language) -> AsyncIterator[str]:
        """Yield answer deltas as the LLM generates them (Alice-style
        pipelining: TTS starts speaking the first sentence while the rest is
        still generating). Falls back to one canned sentence when the model
        yields nothing."""
        hits = await self._retrieve(question)
        context = self._format_context(hits)
        request = LlmRequest(
            system_prompt=self._system_prompt(language),
            user_prompt=self._render_prompt(question, context),
            history=tuple(self._history),
            grammar_gbnf=None,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        parts: list[str] = []
        async for delta in self.llm.stream(request):
            if delta:
                parts.append(delta)
                yield delta
        if not parts:
            fallback = self._fallback(language)
            yield fallback
            return
        self._remember(question, trim_incomplete_tail("".join(parts)))

    async def answer(self, question: str, language: Language) -> GroundedQAResult:
        hits = await self._retrieve(question)
        context = self._format_context(hits)
        request = LlmRequest(
            system_prompt=self._system_prompt(language),
            user_prompt=self._render_prompt(question, context),
            history=tuple(self._history),
            grammar_gbnf=None,  # free-form natural language, not JSON
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        response = await self.llm.generate(request)
        text = trim_incomplete_tail(response.text) or self._fallback(language)
        if response.text.strip():
            self._remember(question, text)
        answer = GroundedAnswer(
            answer=text,
            citations=(),
            confidence=0.75,
            grounding_verdict=GroundingVerdict.PARTIAL,
        )
        return GroundedQAResult(
            answer=answer,
            retrieval_verdict=RetrievalQualityVerdict.PASS,
            grounding_verdict=GroundingJudgeVerdict.SUPPORTED,
            hits=hits,
        )

    async def _retrieve(self, question: str) -> tuple[RetrievalHit, ...]:
        """Best-effort retrieval — never blocks a chat reply."""
        if not self.config.retrieve:
            return ()
        try:
            raw = await self.vector_store.search(
                RetrievalQuery(text=question, top_k=self.config.top_k_retrieve)
            )
            if not raw:
                return ()
            scores = await self.reranker.rerank(question, tuple(h.chunk.content for h in raw))
            ranked = sorted(
                (
                    h.model_copy(update={"rerank_score": s})
                    for h, s in zip(raw, scores, strict=False)
                ),
                key=lambda h: h.rerank_score or 0.0,
                reverse=True,
            )
        except Exception:
            _LOG.warning("conversation.retrieval_failed_degrading_to_chat")
            return ()
        return tuple(ranked[: self.config.top_k_context])

    def _format_context(self, hits: tuple[RetrievalHit, ...]) -> str:
        relevant = [h for h in hits if (h.rerank_score or 0.0) >= self.config.min_context_score]
        if not relevant:
            return ""
        blocks = [f"- {h.chunk.content.strip()}" for h in relevant]
        return "\n".join(blocks)

    def _system_prompt(self, language: Language) -> str:
        if language == Language.RU:
            return self.config.system_prompt_ru
        return self.config.system_prompt_en

    def _render_prompt(self, question: str, context: str) -> str:
        if context:
            return f"Контекст из базы знаний:\n{context}\n\nСообщение: {question}"
        return question

    def _fallback(self, language: Language) -> str:
        if language == Language.RU:
            return "Извини, я не расслышал. Повтори, пожалуйста."
        return "Sorry, I didn't catch that. Could you repeat?"
