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
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from humanoid_robot.domain.knowledge import Citation, GroundedAnswer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, BaseEvent, LlmAnswer, LlmAnswerToken, LlmRejected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.rag.conversation import trim_incomplete_tail
from humanoid_robot.rag.grounded_qa import GroundedQAResult

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
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _subscription: Subscription | None = None
    _inflight: set[asyncio.Task[None]] = field(default_factory=set)

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._subscription = await self.bus.subscribe(AsrFinal.subject, self._on_asr_final)
        _LOG.info("rag_runner.ready")
        try:
            await self._stop.wait()
        finally:
            if self._subscription is not None:
                await self._subscription.cancel()
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

    async def _handle(self, event: AsrFinal) -> None:
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
