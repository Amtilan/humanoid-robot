"""RAG test bridge — operator UI can pose a question without a mic.

Publishes a synthetic ``asr.final`` on the bus, waits for either
``llm.answer`` or ``llm.rejected`` for the same session id, and returns
whichever fires first.  Timeout defaults to 60 s so a slow model does not
hold the UI open forever.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.knowledge import Citation
from humanoid_robot.domain.shared import (
    SessionId,
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, BaseEvent, LlmAnswer, LlmRejected
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


class RagAskRequest(BaseModel):
    """Body of the QA test endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=1, max_length=4096)
    language: Language = Language.RU
    timeout_s: float = Field(default=60.0, gt=0.0, le=300.0)


class RagAskResponse(BaseModel):
    """Result of a QA test round-trip."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    outcome: str  # "answer" | "rejected" | "timeout"
    text: str | None = None
    fallback_text: str | None = None
    reason: str | None = None
    citations: tuple[Citation, ...] = ()


class RagAskStartResponse(BaseModel):
    """Handle for a fire-and-forget QA request tracked over the bus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId


@router.post("/ask", response_model=RagAskResponse)
async def ask(body: RagAskRequest, request: Request) -> RagAskResponse:
    container: AppContainer = request.app.state.container
    bus = container.event_bus
    session_id = new_session_id()

    future: asyncio.Future[BaseEvent] = asyncio.get_running_loop().create_future()

    async def _on_result(event: BaseEvent) -> None:
        if (
            isinstance(event, (LlmAnswer, LlmRejected))
            and event.session_id == session_id
            and not future.done()
        ):
            future.set_result(event)

    answer_sub = await bus.subscribe(LlmAnswer.subject, _on_result)
    rejected_sub = await bus.subscribe(LlmRejected.subject, _on_result)

    try:
        await bus.publish(
            AsrFinal(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer="cortex-core.rag_test",
                ),
                session_id=session_id,
                utterance_id=new_utterance_id(),
                text=body.question,
                language=body.language,
                confidence=1.0,
            )
        )
        try:
            event = await asyncio.wait_for(future, timeout=body.timeout_s)
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"no llm.answer or llm.rejected within {body.timeout_s}s",
            ) from exc
    finally:
        for sub in (answer_sub, rejected_sub):
            with contextlib.suppress(Exception):
                await sub.cancel()

    if isinstance(event, LlmAnswer):
        return RagAskResponse(
            session_id=session_id,
            outcome="answer",
            text=event.text,
            citations=event.citations,
        )
    if isinstance(event, LlmRejected):
        return RagAskResponse(
            session_id=session_id,
            outcome="rejected",
            fallback_text=event.fallback_text,
            reason=event.reason,
        )
    # Defensive — the filter above should preclude this, but keep the API
    # contract simple for the caller.
    return RagAskResponse(session_id=session_id, outcome="timeout")


@router.post("/ask/start", response_model=RagAskStartResponse)
async def ask_start(body: RagAskRequest, request: Request) -> RagAskStartResponse:
    """Publish the ASR event immediately and return the session id.

    The client is expected to subscribe to the WebSocket event stream
    and read `asr.*`, `llm.answer.token`, `llm.answer`, `llm.rejected`
    for the returned `session_id`.  This enables a live pipeline view
    without holding an HTTP connection open for the whole run.
    """
    container: AppContainer = request.app.state.container
    bus = container.event_bus
    session_id = new_session_id()
    await bus.publish(
        AsrFinal(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.rag_test",
            ),
            session_id=session_id,
            utterance_id=new_utterance_id(),
            text=body.question,
            language=body.language,
            confidence=1.0,
        )
    )
    return RagAskStartResponse(session_id=session_id)
