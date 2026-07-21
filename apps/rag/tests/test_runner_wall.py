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
from humanoid_robot.rag.grounded_qa import GroundedQAResult
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
            rejection_reason=None,
            fallback_text=None,
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
