"""Tests for the conversational (RAG-augmented chat) orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from humanoid_robot.domain.knowledge import KnowledgeChunk, RetrievalHit
from humanoid_robot.domain.voice import Language
from humanoid_robot.ports import LlmRequest, LlmResponse, RetrievalQuery
from humanoid_robot.rag.conversation import ConversationConfig, ConversationOrchestrator


@dataclass
class _FakeLlm:
    reply: str = "Привет! Я робот G1."
    last_request: LlmRequest | None = None

    async def generate(self, request: LlmRequest) -> LlmResponse:
        self.last_request = request
        return LlmResponse(
            text=self.reply,
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
        )

    def stream(self, request: LlmRequest) -> AsyncIterator[str]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _FakeVectorStore:
    hits: tuple[RetrievalHit, ...] = ()
    raises: bool = False

    async def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        if self.raises:
            raise RuntimeError("qdrant down")
        return self.hits


@dataclass
class _FakeReranker:
    scores: tuple[float, ...] = ()

    async def rerank(self, query: str, docs: tuple[str, ...]) -> tuple[float, ...]:
        return self.scores or tuple(0.5 for _ in docs)


def _hit(content: str, dense: float = 0.9) -> RetrievalHit:
    chunk = KnowledgeChunk(
        id="c1",
        source_id="s1",
        ordinal=0,
        content=content,
        token_count=len(content.split()),
    )
    return RetrievalHit(chunk=chunk, dense_score=dense)


def _orch(**kw: object) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        vector_store=kw.get("store", _FakeVectorStore()),  # type: ignore[arg-type]
        reranker=kw.get("reranker", _FakeReranker()),  # type: ignore[arg-type]
        llm=kw.get("llm", _FakeLlm()),  # type: ignore[arg-type]
        config=kw.get("config", ConversationConfig()),  # type: ignore[arg-type]
    )


class TestConversation:
    async def test_answers_without_context_pure_chat(self) -> None:
        llm = _FakeLlm(reply="Здравствуй!")
        orch = _orch(store=_FakeVectorStore(hits=()), llm=llm)
        result = await orch.answer("как дела?", Language.RU)
        assert result.answer is not None
        assert result.answer.answer == "Здравствуй!"
        # no context block when nothing retrieved
        assert "Контекст" not in (llm.last_request.user_prompt if llm.last_request else "")

    async def test_includes_context_when_relevant(self) -> None:
        llm = _FakeLlm()
        store = _FakeVectorStore(hits=(_hit("Батарея заряжена на 80%."),))
        orch = _orch(store=store, reranker=_FakeReranker(scores=(0.9,)), llm=llm)
        await orch.answer("какой заряд?", Language.RU)
        assert llm.last_request is not None
        assert "Батарея заряжена" in llm.last_request.user_prompt
        assert llm.last_request.grammar_gbnf is None  # free-form, not JSON

    async def test_low_score_context_dropped(self) -> None:
        llm = _FakeLlm()
        store = _FakeVectorStore(hits=(_hit("нерелевантный текст"),))
        orch = _orch(
            store=store,
            reranker=_FakeReranker(scores=(0.05,)),  # below min_context_score
            llm=llm,
        )
        await orch.answer("привет", Language.RU)
        assert "нерелевантный" not in (llm.last_request.user_prompt if llm.last_request else "")

    async def test_retrieval_error_degrades_to_chat(self) -> None:
        llm = _FakeLlm(reply="Всё хорошо!")
        orch = _orch(store=_FakeVectorStore(raises=True), llm=llm)
        result = await orch.answer("как ты?", Language.RU)
        assert result.answer is not None
        assert result.answer.answer == "Всё хорошо!"

    async def test_empty_llm_reply_uses_fallback(self) -> None:
        orch = _orch(llm=_FakeLlm(reply="   "))
        result = await orch.answer("...", Language.EN)
        assert result.answer is not None
        assert "repeat" in result.answer.answer.lower()

    async def test_english_persona_used(self) -> None:
        llm = _FakeLlm(reply="Hi there!")
        orch = _orch(llm=llm)
        await orch.answer("hello", Language.EN)
        assert llm.last_request is not None
        assert "English" in llm.last_request.system_prompt


class _TrackingStore:
    def __init__(self) -> None:
        self.searched = False

    async def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        self.searched = True
        return ()


async def test_retrieve_false_skips_vector_store() -> None:
    """retrieve=false must not touch the (CPU-bound) embedder/vector store."""
    store = _TrackingStore()
    orch = _orch(store=store, config=ConversationConfig(retrieve=False))
    result = await orch.answer("привет", Language.RU)
    assert store.searched is False
    assert result.answer is not None
    assert result.answer.answer  # still produced a chat reply
