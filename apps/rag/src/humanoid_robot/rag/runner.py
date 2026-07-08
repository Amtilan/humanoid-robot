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
from dataclasses import dataclass, field

from humanoid_robot.domain.knowledge import Citation, GroundedAnswer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, BaseEvent, LlmAnswer, LlmRejected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.rag.grounded_qa import (
    GroundedQAOrchestrator,
    GroundedQAResult,
)

_LOG = get_logger("cortex-rag.runner")


@dataclass(slots=True)
class RagRunner:
    """Long-running consumer of `asr.final` events."""

    orchestrator: GroundedQAOrchestrator
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
        try:
            result = await self.orchestrator.answer(question=event.text, language=event.language)
        except Exception:
            _LOG.exception("rag_runner.orchestrator_failed", session_id=event.session_id)
            await self._publish_rejected(event, reason="orchestrator_error", fallback_text=None)
            return
        await self._publish_result(event, result)

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
