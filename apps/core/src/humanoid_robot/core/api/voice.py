"""Voice output bridge — make the robot speak an exact given text.

Unlike the RAG path (which asks the LLM and speaks its answer), this speaks
the operator's text verbatim. It publishes an ``llm.answer`` on the bus with a
fresh session id, which the voice service's TtsSpeaker (running with
``speak_all_answers``) synthesizes and plays on the robot's speaker. The fresh
session id keeps it out of the dashboard chat panels — it only speaks.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.shared import SessionId, new_correlation_id, new_session_id
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import LlmAnswer, VoiceInterrupt
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


class InterruptResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    interrupted: bool = True


@router.post("/interrupt", response_model=InterruptResponse)
async def interrupt(request: Request) -> InterruptResponse:
    """Stop the robot's speech immediately (dashboard stop button)."""
    container: AppContainer = request.app.state.container
    await container.event_bus.publish(
        VoiceInterrupt(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.voice_interrupt",
            ),
            reason="operator",
        )
    )
    return InterruptResponse()


class SayRequest(BaseModel):
    """Text for the robot to speak out loud, verbatim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    language: Language = Language.RU


class SayResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId


@router.post("/say", response_model=SayResponse)
async def say(body: SayRequest, request: Request) -> SayResponse:
    container: AppContainer = request.app.state.container
    session_id = new_session_id()
    await container.event_bus.publish(
        LlmAnswer(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.voice_say",
            ),
            session_id=session_id,
            text=body.text,
            language=body.language,
            citations=(),
            confidence=1.0,
        )
    )
    return SayResponse(session_id=session_id)
