"""RagRunner tests using InMemoryEventBus + all-fake adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.domain.knowledge import (
    KnowledgeChunk,
    RetrievalHit,
)
from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, LlmAnswer, LlmRejected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.ports.ai import LlmRequest, LlmResponse
from humanoid_robot.ports.knowledge import RetrievalQuery
from humanoid_robot.rag import GroundedQAConfig, GroundedQAOrchestrator
from humanoid_robot.rag.runner import RagRunner
from humanoid_robot.testing import InMemoryEventBus


def _chunk(id_: str, content: str) -> KnowledgeChunk:
    return KnowledgeChunk(id=id_, source_id="s1", ordinal=0, content=content, token_count=8)


def _hit(id_: str, content: str, score: float) -> RetrievalHit:
    return RetrievalHit(chunk=_chunk(id_, content), dense_score=score)


@dataclass(slots=True)
class _FakeStore:
    scripted: tuple[RetrievalHit, ...]

    async def upsert(self, _chunks: tuple[KnowledgeChunk, ...]) -> None:
        return

    async def delete_by_source(self, _sid: str) -> None:
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
    replies: list[str]
    _index: int = 0
    calls: list[LlmRequest] = field(default_factory=list)

    async def generate(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        text = self.replies[min(self._index, len(self.replies) - 1)]
        self._index += 1
        return LlmResponse(text=text, prompt_tokens=1, completion_tokens=1, finish_reason="stop")

    def stream(self, _r: LlmRequest) -> AsyncIterator[str]:  # pragma: no cover
        raise NotImplementedError


def _asr_event(session_id: str, text: str, language: Language) -> AsrFinal:
    return AsrFinal(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=session_id,  # type: ignore[arg-type]
        utterance_id=new_utterance_id(),
        text=text,
        language=language,
        confidence=0.9,
    )


async def _wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        await asyncio.sleep(0.01)
        if condition():
            return
    msg = "timed out waiting for condition"
    raise AssertionError(msg)


class TestRagRunner:
    async def test_supported_answer_is_published(self) -> None:
        hit1 = _hit("c1", "Робот работает полностью офлайн.", 0.9)
        hit2 = _hit("c2", "Второй релевантный источник для покрытия.", 0.7)
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
            config=GroundedQAConfig(min_top1_rerank_score=0.3, min_chunk_coverage=1),
        )
        bus = InMemoryEventBus()
        runner = RagRunner(orchestrator=orch, bus=bus)
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)  # let the runner subscribe

        session_id = new_session_id()
        await bus.publish(_asr_event(session_id, "Работает ли робот офлайн?", Language.RU))

        await _wait_for(lambda: any(isinstance(ev, LlmAnswer) for ev in bus.published))
        runner.request_stop()
        await run_task

        answer = next(ev for ev in bus.published if isinstance(ev, LlmAnswer))
        assert answer.session_id == session_id
        assert answer.text == "Работает офлайн."
        assert answer.language == Language.RU

    async def test_low_score_publishes_rejection(self) -> None:
        hit = _hit("c1", "неподходящий текст", 0.1)
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=(hit,)),
            reranker=_FakeReranker(scripted={hit.chunk.content: 0.1}),
            llm=_ScriptedLlm(replies=[]),
            config=GroundedQAConfig(min_top1_rerank_score=0.6, min_chunk_coverage=1),
        )
        bus = InMemoryEventBus()
        runner = RagRunner(orchestrator=orch, bus=bus)
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)

        session_id = new_session_id()
        await bus.publish(_asr_event(session_id, "…", Language.RU))

        await _wait_for(lambda: any(isinstance(ev, LlmRejected) for ev in bus.published))
        runner.request_stop()
        await run_task

        rej = next(ev for ev in bus.published if isinstance(ev, LlmRejected))
        assert rej.session_id == session_id
        assert rej.reason == "fail_low_score"
        assert rej.fallback_text  # human-facing "no answer" reply

    async def test_ignores_non_asr_events(self) -> None:
        orch = GroundedQAOrchestrator(
            vector_store=_FakeStore(scripted=()),
            reranker=_FakeReranker(scripted={}),
            llm=_ScriptedLlm(replies=[]),
        )
        bus = InMemoryEventBus()
        runner = RagRunner(orchestrator=orch, bus=bus)
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)

        # Publish an unrelated event and confirm nothing is emitted.
        await bus.publish(
            LlmAnswer(
                meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
                session_id=new_session_id(),
                text="ignored",
                language=Language.RU,
                citations=(),
                confidence=0.0,
            )
        )
        await asyncio.sleep(0.05)

        runner.request_stop()
        await run_task

        emitted = [ev for ev in bus.published if isinstance(ev, LlmRejected)]
        assert emitted == []

    async def test_orchestrator_exception_publishes_rejection(self) -> None:
        @dataclass(slots=True)
        class _Boom:
            async def answer(self, *_a: Any, **_kw: Any) -> None:
                msg = "kaboom"
                raise RuntimeError(msg)

        bus = InMemoryEventBus()
        runner = RagRunner(orchestrator=_Boom(), bus=bus)  # type: ignore[arg-type]
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)

        session_id = new_session_id()
        await bus.publish(_asr_event(session_id, "boom?", Language.RU))
        await _wait_for(lambda: any(isinstance(ev, LlmRejected) for ev in bus.published))
        runner.request_stop()
        await run_task

        rej = next(ev for ev in bus.published if isinstance(ev, LlmRejected))
        assert rej.reason == "orchestrator_error"
