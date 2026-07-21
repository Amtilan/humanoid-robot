"""RagRunner guard mode — the interview intercepts asr.final end-to-end."""

from __future__ import annotations

import asyncio

from humanoid_robot.domain.knowledge import GroundedAnswer, GroundingVerdict
from humanoid_robot.domain.shared import new_correlation_id, new_session_id
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, LlmAnswer, VisitCardCompleted, VisitIntakeStart
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.rag.grounded_qa import (
    GroundedQAResult,
    GroundingJudgeVerdict,
    RetrievalQualityVerdict,
)
from humanoid_robot.rag.runner import RagRunner
from humanoid_robot.testing import InMemoryEventBus


class _EchoOrchestrator:
    """Free-chat stand-in; guard mode must bypass it during the interview."""

    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, question: str, language: Language) -> GroundedQAResult:
        self.calls += 1
        answer = GroundedAnswer(
            answer="чат-ответ",
            citations=(),
            confidence=0.75,
            grounding_verdict=GroundingVerdict.PARTIAL,
        )
        return GroundedQAResult(
            answer=answer,
            retrieval_verdict=RetrievalQualityVerdict.PASS,
            grounding_verdict=GroundingJudgeVerdict.SUPPORTED,
            hits=(),
        )


def _asr(text: str) -> AsrFinal:
    return AsrFinal(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=new_session_id(),
        utterance_id="utt_test",  # type: ignore[arg-type]
        text=text,
        language=Language.RU,
        confidence=1.0,
    )


async def _drain(runner_task: asyncio.Task[None], runner: RagRunner) -> None:
    runner.request_stop()
    await runner_task


async def test_interview_from_start_event_to_completed_card() -> None:
    bus = InMemoryEventBus()
    orch = _EchoOrchestrator()
    runner = RagRunner(orchestrator=orch, bus=bus, guard_intake_enabled=True)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)  # let subscriptions land

    await bus.publish(
        VisitIntakeStart(
            meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
            actor="guard-panel",
        )
    )
    for utterance in (
        "Иванов Иван Иванович",
        "ТОО Транспорт",
        "Совещание",
        "Отдел кадров",
        "да",
        "да",
        "да, всё верно",
    ):
        await bus.publish(_asr(utterance))
        await asyncio.sleep(0.01)  # runner handles events in spawned tasks

    cards = [e for e in bus.published if isinstance(e, VisitCardCompleted)]
    assert len(cards) == 1
    assert cards[0].full_name == "Иванов Иван Иванович"
    assert cards[0].has_pass is True
    # The orchestrator was never consulted during the interview.
    assert orch.calls == 0
    # Every step produced a spoken reply.
    answers = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert len(answers) >= 8  # greeting + 6 steps + completion

    await _drain(task, runner)


async def test_voice_trigger_starts_interview() -> None:
    bus = InMemoryEventBus()
    orch = _EchoOrchestrator()
    runner = RagRunner(orchestrator=orch, bus=bus, guard_intake_enabled=True)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)

    await bus.publish(_asr("Здравствуйте, я хочу оформить визит"))
    await asyncio.sleep(0.01)
    answers = [e for e in bus.published if isinstance(e, LlmAnswer)]
    assert any("фамилию" in a.text for a in answers)
    assert orch.calls == 0

    await _drain(task, runner)


async def test_free_chat_unaffected_when_not_engaged() -> None:
    bus = InMemoryEventBus()
    orch = _EchoOrchestrator()
    runner = RagRunner(orchestrator=orch, bus=bus, guard_intake_enabled=True)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)

    await bus.publish(_asr("Какая сегодня погода?"))
    await asyncio.sleep(0.01)
    assert orch.calls == 1

    await _drain(task, runner)
