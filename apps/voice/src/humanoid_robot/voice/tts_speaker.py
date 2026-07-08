"""Output side — subscribe to LlmAnswer, synthesize with TtsPort, play on AudioOutPort.

Kept separate from `VoiceSession` (input side) so each concern owns one state
machine. The two share the same session id via the runner.
"""

from __future__ import annotations

from dataclasses import dataclass

from humanoid_robot.domain.shared import (
    SessionId,
    UtteranceId,
    new_correlation_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import (
    BaseEvent,
    LlmAnswer,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    AudioOutPort,
    EventBusPort,
    Subscription,
    TtsPort,
    TtsRequest,
)

_LOG = get_logger("cortex-voice.tts")


@dataclass(slots=True)
class TtsSpeaker:
    """Subscribes to `llm.answer` events and drives TTS→speaker output."""

    tts: TtsPort
    audio_out: AudioOutPort
    bus: EventBusPort
    session_id: SessionId
    producer: str = "cortex-voice"

    async def start(self) -> Subscription:
        """Subscribe to `llm.answer` — returns the handle for later cancel."""
        return await self.bus.subscribe(LlmAnswer.subject, self._on_llm_answer)

    async def _on_llm_answer(self, event: BaseEvent) -> None:
        if not isinstance(event, LlmAnswer):
            return
        if event.session_id != self.session_id:
            return
        utterance_id = new_utterance_id()
        await self._publish_started(utterance_id)
        duration_ms = 0
        try:
            async for frame in self.tts.synthesize_stream(
                TtsRequest(text=event.text, language=self._language_for_event(event))
            ):
                await self.audio_out.play(frame)
                duration_ms += _frame_ms(frame)
        finally:
            await self._publish_finished(utterance_id, duration_ms)

    def _language_for_event(self, event: LlmAnswer) -> Language:
        return getattr(event, "language", Language.RU)

    async def _publish_started(self, utterance_id: UtteranceId) -> None:
        await self.bus.publish(
            TtsSynthesisStarted(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=self.session_id,
                utterance_id=utterance_id,
            )
        )

    async def _publish_finished(self, utterance_id: UtteranceId, duration_ms: int) -> None:
        await self.bus.publish(
            TtsSynthesisFinished(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=self.session_id,
                utterance_id=utterance_id,
                duration_ms=duration_ms,
            )
        )


def _frame_ms(frame: object) -> int:
    """Approximate a frame's duration in ms from its PCM + format."""
    pcm: bytes = getattr(frame, "pcm", b"")
    fmt = getattr(frame, "format", None)
    if fmt is None or not pcm:
        return 0
    bytes_per_second = int(fmt.bytes_per_second)
    return len(pcm) * 1000 // bytes_per_second
