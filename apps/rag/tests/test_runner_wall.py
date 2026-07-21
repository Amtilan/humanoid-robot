"""RagRunner + wall intent: matched commands bypass the LLM entirely."""

from __future__ import annotations

from humanoid_robot.domain.knowledge import GroundedAnswer
from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.domain.wall import WallCommandKind, WallSection
from humanoid_robot.events import AsrFinal, LlmAnswer, WallCommandRequested
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.rag.grounded_qa import GroundedQAResult, RetrievalQualityVerdict
from humanoid_robot.rag.runner import RagRunner
from humanoid_robot.rag.wall_intent import WallIntentMatcher
from humanoid_robot.testing import InMemoryEventBus


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def answer(self, question: str, language: Language) -> GroundedQAResult:
        self.calls.append(question)
        return GroundedQAResult(
            answer=GroundedAnswer(answer="llm reply", citations=(), confidence=0.9),
            retrieval_verdict=RetrievalQualityVerdict.PASS,
            grounding_verdict=None,
        )


def _asr(text: str) -> AsrFinal:
    return AsrFinal(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="test"),
        session_id=new_session_id(),
        utterance_id=new_utterance_id(),
        text=text,
        language=Language.RU,
        confidence=0.9,
    )


async def test_wall_command_bypasses_llm() -> None:
    bus = InMemoryEventBus()
    orchestrator = _FakeOrchestrator()
    runner = RagRunner(orchestrator=orchestrator, bus=bus, wall_intent=WallIntentMatcher())

    await runner._handle(_asr("покажи аэропорт Зайсан"))

    assert orchestrator.calls == []  # LLM untouched
    requested = [e for e in bus.published if isinstance(e, WallCommandRequested)]
    assert len(requested) == 1
    assert requested[0].command.kind is WallCommandKind.OPEN_SECTION
    assert requested[0].command.section is WallSection.AERO1
    assert requested[0].source == "voice"

    spoken = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert len(spoken) == 1
    assert "Зайсан" in spoken[0].text


async def test_non_command_reaches_llm() -> None:
    bus = InMemoryEventBus()
    orchestrator = _FakeOrchestrator()
    runner = RagRunner(orchestrator=orchestrator, bus=bus, wall_intent=WallIntentMatcher())

    await runner._handle(_asr("расскажи анекдот про роботов"))

    assert orchestrator.calls == ["расскажи анекдот про роботов"]
    assert not [e for e in bus.published if isinstance(e, WallCommandRequested)]


async def test_greeting_on_visitor_with_cooldown() -> None:
    from humanoid_robot.events import VisitorDetected

    bus = InMemoryEventBus()
    runner = RagRunner(
        orchestrator=_FakeOrchestrator(),
        bus=bus,
        greeting_text="Здравствуйте! Я робот-презентатор.",
        greeting_cooldown_s=120.0,
    )

    def _visitor() -> VisitorDetected:
        return VisitorDetected(
            meta=EventMetadata(correlation_id=new_correlation_id(), producer="test"),
            score=0.2,
        )

    await runner._on_visitor_detected(_visitor())
    await runner._on_visitor_detected(_visitor())

    greetings = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert len(greetings) == 1  # second detection suppressed
    assert "робот-презентатор" in greetings[0].text

    runner._last_greeting_at = float("-inf")
    await runner._on_visitor_detected(_visitor())
    greetings = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert len(greetings) == 2


async def test_fact_question_answers_instead_of_switching() -> None:
    """«Какая протяжённость дороги X?» must answer the fact, not open the
    section (the intent matcher must not steal fact questions)."""
    import asyncio as _asyncio

    from humanoid_robot.rag.presenter_kb import PresenterKb
    from humanoid_robot.testing import InMemoryEventBus

    bus = InMemoryEventBus()
    kb = PresenterKb(
        sections={
            "Avto1": {
                "name_ru": "автодорога Кызылорда — Жезказган",
                "length_ru": "208 км",
            }
        }
    )
    runner = RagRunner(
        orchestrator=_FakeOrchestrator(),
        bus=bus,
        wall_intent=WallIntentMatcher(),
        presenter_kb=kb,
    )
    task = _asyncio.create_task(runner.run())
    await _asyncio.sleep(0)
    await bus.publish(_asr("Какая протяжённость дороги Кызылорда — Жезказган?"))
    await _asyncio.sleep(0.05)

    walls = [e for e in bus.published if isinstance(e, WallCommandRequested)]
    answers = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert walls == []
    assert any("208" in a.text for a in answers)
    runner.request_stop()
    await task
