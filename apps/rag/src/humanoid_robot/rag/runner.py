"""RAG runner — subscribes to `asr.final` and publishes `llm.answer` / `llm.rejected`.

Concerns are strictly separated:
    - `GroundedQAOrchestrator` (see grounded_qa.py) has the retrieval + LLM
      + guardrail logic. It knows nothing about the event bus.
    - `RagRunner` here owns the NATS wiring: subscribes to `asr.final`,
      dispatches each event through the orchestrator, and publishes the
      resulting `LlmAnswer` or `LlmRejected`.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from humanoid_robot.domain.knowledge import Citation, GroundedAnswer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import (
    AsrFinal,
    BaseEvent,
    LlmAnswer,
    LlmAnswerToken,
    LlmRejected,
    VisitCardCompleted,
    VisitIntakeStart,
    WallCommandRequested,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.rag.conversation import trim_incomplete_tail
from humanoid_robot.rag.grounded_qa import GroundedQAResult
from humanoid_robot.rag.guard_kb import GuardKb
from humanoid_robot.rag.visit_intake import VisitIntake, wants_intake
from humanoid_robot.rag.wall_intent import WallIntentMatch, WallIntentMatcher

_LOG = get_logger("cortex-rag.runner")

# Conversation replies carry no verbatim citations; this mirrors the fixed
# confidence the ConversationOrchestrator assigns to chat answers.
_STREAM_CONFIDENCE = 0.75


class QaOrchestrator(Protocol):
    """Either the grounded or conversational orchestrator — both answer the
    same way (`asr.final` text in, a `GroundedQAResult` out)."""

    async def answer(self, question: str, language: Language) -> GroundedQAResult: ...


class _StreamFn(Protocol):
    def __call__(self, *, question: str, language: Language) -> AsyncIterator[str]: ...


@dataclass(slots=True)
class RagRunner:
    """Long-running consumer of `asr.final` events."""

    orchestrator: QaOrchestrator
    bus: EventBusPort
    producer: str = "cortex-rag"
    # Security-desk mode: when enabled, «оформите визит»-style phrases (or a
    # visit.intake.start event from the guard panel) run the deterministic
    # visitor interview instead of free chat.
    guard_intake_enabled: bool = False
    # Customer reference data; room/unit navigation answers are deterministic.
    guard_kb: GuardKb | None = None
    # Presenter mode: voice commands that drive the video wall bypass the LLM.
    wall_intent: WallIntentMatcher | None = None
    _intake: VisitIntake = field(default_factory=VisitIntake)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _subscription: Subscription | None = None
    _intake_subscription: Subscription | None = None
    _inflight: set[asyncio.Task[None]] = field(default_factory=set)

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._subscription = await self.bus.subscribe(AsrFinal.subject, self._on_asr_final)
        if self.guard_intake_enabled:
            self._intake_subscription = await self.bus.subscribe(
                VisitIntakeStart.subject, self._on_intake_start
            )
        _LOG.info("rag_runner.ready", guard_intake=self.guard_intake_enabled)
        try:
            await self._stop.wait()
        finally:
            if self._subscription is not None:
                await self._subscription.cancel()
            if self._intake_subscription is not None:
                await self._intake_subscription.cancel()
            for task in list(self._inflight):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._inflight.clear()

    async def _on_asr_final(self, event: BaseEvent) -> None:
        if not isinstance(event, AsrFinal):
            return
        task = asyncio.create_task(self._handle(event), name=f"rag-answer[{event.session_id}]")
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _on_intake_start(self, event: BaseEvent) -> None:
        if not isinstance(event, VisitIntakeStart):
            return
        _LOG.info("visit_intake.started", actor=event.actor)
        await self._publish_answer_text(session_id="guard-intake", text=self._intake.start())

    async def _handle_intake(self, event: AsrFinal) -> None:
        reply, card = self._intake.consume(event.text)
        if card is not None:
            await self.bus.publish(
                VisitCardCompleted(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.producer,
                    ),
                    language=str(event.language.value),
                    full_name=str(card.get("full_name", "")),
                    organization=str(card.get("organization", "")),
                    purpose=str(card.get("purpose", "")),
                    destination=str(card.get("destination", "")),
                    has_pass=card.get("has_pass"),  # type: ignore[arg-type]
                    has_id=card.get("has_id"),  # type: ignore[arg-type]
                )
            )
            _LOG.info("visit_intake.completed", full_name=card.get("full_name"))
        if reply:
            await self._publish_answer_text(session_id=event.session_id, text=reply)

    async def _publish_answer_text(
        self, *, session_id: str, text: str, language: Language = Language.RU
    ) -> None:
        """Publish a deterministic (non-LLM) spoken line as a normal
        llm.answer, so TTS and the dashboard treat it like any reply."""
        await self.bus.publish(
            LlmAnswer(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=session_id,  # type: ignore[arg-type]
                text=text,
                language=language,
                citations=(),
                confidence=1.0,
            )
        )

    async def _handle_wall_match(self, event: AsrFinal, match: WallIntentMatch) -> None:
        """Deterministic wall command: request it and voice the accompaniment."""
        command_id = str(uuid.uuid4())
        await self.bus.publish(
            WallCommandRequested(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                command_id=command_id,
                command=match.command,
                source="voice",
                language=str(match.language.value),
                utterance=event.text[:200],
            )
        )
        _LOG.info(
            "wall_intent.matched",
            command=(match.command.section or match.command.nav),
            text=event.text[:60],
        )
        await self._publish_answer_text(
            session_id=event.session_id, text=match.speak, language=match.language
        )

    async def _handle(self, event: AsrFinal) -> None:
        # Presenter fast path: wall commands never reach the LLM.
        if self.wall_intent is not None:
            match = self.wall_intent.match(event.text)
            if match is not None:
                await self._handle_wall_match(event, match)
                return
        # Security-desk interview intercepts the utterance before free chat.
        if self.guard_intake_enabled:
            if self._intake.engaged:
                await self._handle_intake(event)
                return
            if wants_intake(event.text):
                _LOG.info("visit_intake.triggered_by_voice", text=event.text[:60])
                await self._publish_answer_text(
                    session_id=event.session_id, text=self._intake.start()
                )
                return
            if self.guard_kb is not None:
                answer = self.guard_kb.lookup(event.text)
                if answer is not None:
                    _LOG.info("guard_kb.navigation_answer", text=event.text[:60])
                    await self._publish_answer_text(session_id=event.session_id, text=answer)
                    return
        # Prefer the streaming path when the orchestrator supports it: tokens
        # go out as llm.answer.token so TTS/dashboards can start on the first
        # sentence while the model is still generating (the final llm.answer
        # still follows for consumers that only want the completed text).
        stream_fn = getattr(self.orchestrator, "stream_answer", None)
        if stream_fn is not None:
            await self._handle_streaming(event, stream_fn)
            return
        try:
            result = await self.orchestrator.answer(question=event.text, language=event.language)
        except Exception:
            _LOG.exception("rag_runner.orchestrator_failed", session_id=event.session_id)
            await self._publish_rejected(event, reason="orchestrator_error", fallback_text=None)
            return
        await self._publish_result(event, result)

    async def _handle_streaming(
        self,
        event: AsrFinal,
        stream_fn: _StreamFn,
    ) -> None:
        parts: list[str] = []
        sequence = 0
        try:
            async for delta in stream_fn(question=event.text, language=event.language):
                parts.append(delta)
                await self.bus.publish(
                    LlmAnswerToken(
                        meta=EventMetadata(
                            correlation_id=new_correlation_id(),
                            producer=self.producer,
                        ),
                        session_id=event.session_id,
                        sequence=sequence,
                        delta_text=delta,
                    )
                )
                sequence += 1
        except Exception:
            _LOG.exception("rag_runner.stream_failed", session_id=event.session_id)
            if not parts:
                await self._publish_rejected(event, reason="orchestrator_error", fallback_text=None)
                return
            # Partial answer survives — publish what we have so TTS finishes
            # the sentence rather than cutting to silence.
        # A max_tokens-truncated tail is cut to the last finished sentence so
        # the chat text matches what TTS actually says out loud.
        text = trim_incomplete_tail("".join(parts))
        if not text:
            await self._publish_rejected(event, reason="empty_answer", fallback_text=None)
            return
        await self.bus.publish(
            LlmAnswer(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=event.session_id,
                text=text,
                language=self._language_for_response(event.language),
                citations=(),
                confidence=_STREAM_CONFIDENCE,
            )
        )

    async def _publish_result(self, event: AsrFinal, result: GroundedQAResult) -> None:
        if result.answer is not None:
            await self._publish_answer(event, result.answer)
            return
        await self._publish_rejected(
            event,
            reason=result.rejection_reason or "unknown",
            fallback_text=result.fallback_text,
        )

    async def _publish_answer(self, event: AsrFinal, answer: GroundedAnswer) -> None:
        await self.bus.publish(
            LlmAnswer(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=event.session_id,
                text=answer.answer,
                language=self._language_for_response(event.language),
                citations=tuple(
                    Citation(chunk_id=c.chunk_id, quote=c.quote) for c in answer.citations
                ),
                confidence=answer.confidence,
            )
        )

    async def _publish_rejected(
        self,
        event: AsrFinal,
        *,
        reason: str,
        fallback_text: str | None,
    ) -> None:
        await self.bus.publish(
            LlmRejected(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=event.session_id,
                reason=reason,
                fallback_text=fallback_text,
            )
        )

    def _language_for_response(self, language: Language) -> Language:
        return Language.RU if language is Language.UNKNOWN else language
