"""Voice session — orchestrates mic → VAD → ASR → NATS events.

Design principles:
    - `VoiceSession` owns the state machine (IDLE → LISTENING → DECODING →
      IDLE). Everything else is a Port.
    - The session is a pure asyncio coroutine driven by `run()` — no threads,
      no globals. Ports do the heavy lifting.
    - Testable end-to-end with in-memory fakes: `MockVad`, `MockAsr`,
      `InMemoryEventBus`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.shared import (
    SessionId,
    UtteranceId,
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, SpeechDetected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    AsrPort,
    AudioFrame,
    EventBusPort,
    VadDecision,
    VadPort,
)

_LOG = get_logger("cortex-voice.session")


class VoiceSessionState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    DECODING = "decoding"


class VoiceSessionConfig(BaseModel):
    """Runtime parameters for one voice session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    language_hint: Language = Language.RU
    min_speech_ms: int = Field(default=200, ge=50, le=2000)
    silence_hang_ms: int = Field(default=600, ge=100, le=3000)
    max_utterance_ms: int = Field(default=10_000, ge=1000, le=60_000)
    producer: str = "cortex-voice"


@dataclass(slots=True)
class VoiceSession:
    """One session — takes an async mic iterator, publishes events until stop."""

    vad: VadPort
    asr: AsrPort
    bus: EventBusPort
    config: VoiceSessionConfig = field(default_factory=VoiceSessionConfig)
    session_id: SessionId = field(default_factory=new_session_id)
    _state: VoiceSessionState = field(default=VoiceSessionState.IDLE, init=False)
    _speech_buffer: bytearray = field(default_factory=bytearray, init=False)
    _speech_ms: int = field(default=0, init=False)
    _silence_ms: int = field(default=0, init=False)
    _current_utterance_id: UtteranceId | None = field(default=None, init=False)

    @property
    def state(self) -> VoiceSessionState:
        return self._state

    async def run(self, frames: AsyncIterator[AudioFrame]) -> None:
        """Consume the mic stream until it ends; publish events along the way."""
        async for frame in frames:
            await self._handle(frame)
        # Stream ended — flush any in-flight utterance.
        if self._state != VoiceSessionState.IDLE and self._speech_buffer:
            await self._finalize(frame.format.sample_rate_hz)

    async def _handle(self, frame: AudioFrame) -> None:
        decision = await self.vad.decide(frame)
        frame_ms = len(frame.pcm) * 1000 // frame.format.bytes_per_second

        if decision.is_speech:
            await self._on_speech(frame, decision, frame_ms)
        else:
            await self._on_silence(frame, frame_ms)

    async def _on_speech(self, frame: AudioFrame, decision: VadDecision, frame_ms: int) -> None:
        if self._state == VoiceSessionState.IDLE:
            self._state = VoiceSessionState.LISTENING
            self._current_utterance_id = new_utterance_id()
            self._speech_ms = 0
            self._silence_ms = 0
            self._speech_buffer.clear()
            await self._publish_speech_detected(
                start_ms=self._speech_ms,
                end_ms=self._speech_ms + frame_ms,
                energy_db=_prob_to_db(decision.speech_probability),
            )
        self._speech_buffer.extend(frame.pcm)
        self._speech_ms += frame_ms
        self._silence_ms = 0
        if self._speech_ms >= self.config.max_utterance_ms:
            await self._finalize(frame.format.sample_rate_hz)

    async def _on_silence(self, frame: AudioFrame, frame_ms: int) -> None:
        if self._state == VoiceSessionState.IDLE:
            return
        self._silence_ms += frame_ms
        if (
            self._speech_ms >= self.config.min_speech_ms
            and self._silence_ms >= self.config.silence_hang_ms
        ):
            await self._finalize(frame.format.sample_rate_hz)
        elif self._silence_ms >= self.config.silence_hang_ms:
            # Not enough speech accumulated → drop the utterance.
            self._state = VoiceSessionState.IDLE
            self._speech_buffer.clear()

    async def _finalize(self, sample_rate_hz: int) -> None:
        self._state = VoiceSessionState.DECODING
        utterance_id = self._current_utterance_id or new_utterance_id()
        payload = bytes(self._speech_buffer)
        self._speech_buffer.clear()
        transcription = await self.asr.transcribe_batch(
            payload,
            sample_rate_hz=sample_rate_hz,
            language_hint=self.config.language_hint,
        )
        await self.bus.publish(
            AsrFinal(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.config.producer,
                ),
                session_id=self.session_id,
                utterance_id=utterance_id,
                text=transcription.text,
                language=transcription.language,
                confidence=transcription.confidence,
            )
        )
        self._state = VoiceSessionState.IDLE
        self._current_utterance_id = None
        self._speech_ms = 0
        self._silence_ms = 0

    async def _publish_speech_detected(
        self, *, start_ms: int, end_ms: int, energy_db: float
    ) -> None:
        await self.bus.publish(
            SpeechDetected(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.config.producer,
                ),
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                energy_db=energy_db,
            )
        )


def _prob_to_db(prob: float) -> float:
    # Log-space mapping for a probability [0,1] to a decibel-like scalar.
    # Only used for observability, not for gating.
    if prob <= 0.0:
        return -120.0
    import math  # noqa: PLC0415

    return 20.0 * math.log10(max(prob, 1e-6))
