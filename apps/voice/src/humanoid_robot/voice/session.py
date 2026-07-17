"""Voice session — orchestrates mic → VAD → (wake-word gate) → ASR → NATS events.

Design principles:
    - `VoiceSession` owns the state machine (IDLE → LISTENING → DECODING →
      IDLE). Everything else is a Port.
    - Wake-word is optional. When configured, the session only starts
      LISTENING after a wake-word event and returns to IDLE after each
      utterance is decoded.
    - The session is a pure asyncio coroutine driven by `run()` — no threads,
      no globals. Ports do the heavy lifting.
    - Testable end-to-end with in-memory fakes: `FakeVad`, `FakeWakeWord`,
      `FakeAsr`, `InMemoryEventBus`.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
from humanoid_robot.events import AsrFinal, SpeechDetected, WakeWordTriggered
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    AsrPort,
    AudioFrame,
    EventBusPort,
    VadDecision,
    VadPort,
    WakeWordPort,
)

_LOG = get_logger("cortex-voice.session")

# Similarity threshold for the fuzzy wake-name match on the first word.
_WAKE_FUZZY_RATIO = 0.6
# Longest utterance still treated as a possible "Слуга, ..." barge-in while
# the robot is speaking; longer captures are its own speaker echo.
_MAX_BARGE_UTTERANCE_MS = 3000


class VoiceSessionState(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
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
    # When true, listening only starts after a wake-word. When false, VAD
    # is the sole trigger.
    require_wake_word: bool = False
    # Grace period after wake-word during which we accept speech even before
    # VAD has picked it up (helps with quiet openers).
    wake_word_grace_ms: int = Field(default=1500, ge=0, le=10_000)
    # Transcript-level name gate: when set, an utterance is only forwarded to
    # the LLM if its transcript mentions this name (case-insensitive; matched on
    # the first 4 chars so Russian declensions "Слуга/Слугу/Слуге" all trigger).
    # Reuses the always-on ASR — no separate wake-word model needed.
    wake_name: str | None = None
    # "always"          — every forwarded utterance must mention the name.
    # "interrupt_only"  — free-flowing dialogue: any speech is answered while
    #                     the robot is silent, but while it is SPEAKING only an
    #                     utterance with the name gets through (and cuts it
    #                     off). Doubles as self-echo protection.
    wake_name_mode: str = "always"


@dataclass(slots=True)
class VoiceSession:
    """One session — takes an async mic iterator, publishes events until stop."""

    vad: VadPort
    asr: AsrPort
    bus: EventBusPort
    wake_word: WakeWordPort | None = None
    config: VoiceSessionConfig = field(default_factory=VoiceSessionConfig)
    session_id: SessionId = field(default_factory=new_session_id)
    # Barge-in hook — the runner wires it to TtsSpeaker.interrupt. In
    # "interrupt_only" mode it fires from the decode path when the transcript
    # contains the wake name while the robot is speaking.
    on_user_speech: Callable[[], Awaitable[None]] | None = None
    # Runner-wired probe: is the robot speaking right now (TtsSpeaker.speaking)?
    speaker_is_speaking: Callable[[], bool] | None = None
    _state: VoiceSessionState = field(default=VoiceSessionState.IDLE, init=False)
    _speech_buffer: bytearray = field(default_factory=bytearray, init=False)
    _speech_ms: int = field(default=0, init=False)
    _silence_ms: int = field(default=0, init=False)
    _armed_grace_ms: int = field(default=0, init=False)
    _current_utterance_id: UtteranceId | None = field(default=None, init=False)
    _decode_tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False)
    _decode_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    # True if ANY frame of the current utterance was captured while the robot
    # was speaking — the policy must use capture-time state, not decode-time
    # (echo decoded after speech ends would otherwise read as user speech and
    # the robot would answer itself in a loop).
    _captured_while_speaking: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not self.config.require_wake_word:
            self._state = VoiceSessionState.IDLE
        else:
            self._state = VoiceSessionState.IDLE  # will move to ARMED on wake-word

    @property
    def state(self) -> VoiceSessionState:
        return self._state

    async def run(self, frames: AsyncIterator[AudioFrame]) -> None:
        """Consume the mic stream until it ends; publish events along the way."""
        last_frame: AudioFrame | None = None
        async for frame in frames:
            last_frame = frame
            await self._handle(frame)
        # Stream ended — flush any in-flight utterance.
        if (
            self._state in (VoiceSessionState.LISTENING, VoiceSessionState.ARMED)
            and self._speech_buffer
            and last_frame is not None
        ):
            await self._finalize(last_frame.format.sample_rate_hz)
        # Decodes run in the background; let them land before the session ends.
        if self._decode_tasks:
            await asyncio.gather(*self._decode_tasks, return_exceptions=True)

    async def _handle(self, frame: AudioFrame) -> None:
        frame_ms = len(frame.pcm) * 1000 // frame.format.bytes_per_second

        if self.config.require_wake_word and self._state == VoiceSessionState.IDLE:
            await self._check_wake_word(frame)
            return

        decision = await self.vad.decide(frame)
        if decision.is_speech:
            await self._on_speech(frame, decision, frame_ms)
        else:
            await self._on_silence(frame, frame_ms)

    async def _check_wake_word(self, frame: AudioFrame) -> None:
        if self.wake_word is None:
            return
        event = await self.wake_word.feed(frame)
        if event is None:
            return
        self._state = VoiceSessionState.ARMED
        self._armed_grace_ms = self.config.wake_word_grace_ms
        await self.bus.publish(
            WakeWordTriggered(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.config.producer,
                ),
                session_id=self.session_id,
                word=event.word,
                confidence=event.score,
            )
        )

    async def _on_speech(self, frame: AudioFrame, decision: VadDecision, frame_ms: int) -> None:
        if self._state in (VoiceSessionState.IDLE, VoiceSessionState.ARMED):
            self._state = VoiceSessionState.LISTENING
            self._current_utterance_id = new_utterance_id()
            self._speech_ms = 0
            self._silence_ms = 0
            self._speech_buffer.clear()
            self._captured_while_speaking = False
            await self._publish_speech_detected(
                start_ms=self._speech_ms,
                end_ms=self._speech_ms + frame_ms,
                energy_db=_prob_to_db(decision.speech_probability),
            )
        if self.speaker_is_speaking is not None and self.speaker_is_speaking():
            self._captured_while_speaking = True
        self._speech_buffer.extend(frame.pcm)
        self._speech_ms += frame_ms
        self._silence_ms = 0
        if self._speech_ms >= self.config.max_utterance_ms:
            await self._finalize(frame.format.sample_rate_hz)

    async def _on_silence(self, frame: AudioFrame, frame_ms: int) -> None:
        if self._state == VoiceSessionState.IDLE:
            return
        if self._state == VoiceSessionState.ARMED:
            self._armed_grace_ms = max(0, self._armed_grace_ms - frame_ms)
            if self._armed_grace_ms == 0:
                # No speech within the wake-word grace period — return to IDLE.
                self._state = VoiceSessionState.IDLE
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
        """Snapshot the utterance and decode it in a BACKGROUND task.

        Awaiting whisper inline froze the mic loop for the whole decode
        (~2-3 s): arecord's pipe backed up, audio spoken meanwhile was lost
        and the mic appeared to "cut out". Continuous listening (Alice-style)
        means the frame loop returns to IDLE immediately and keeps consuming
        while decoding runs concurrently (serialized by `_decode_lock` so
        parallel whisper calls don't thrash the CPU).
        """
        utterance_id = self._current_utterance_id or new_utterance_id()
        payload = bytes(self._speech_buffer)
        captured_while_speaking = self._captured_while_speaking
        self._speech_buffer.clear()
        self._state = VoiceSessionState.IDLE
        self._current_utterance_id = None
        self._speech_ms = 0
        self._silence_ms = 0
        self._captured_while_speaking = False
        # Cheap echo shed: an utterance captured while the robot was talking
        # that is LONGER than any realistic "Слуга, стоп" is the robot's own
        # speaker bleeding into the mic — don't burn whisper CPU on it (that
        # contention is what tears the robot's speech apart).
        duration_ms = len(payload) * 1000 // (sample_rate_hz * 2)
        if captured_while_speaking and duration_ms > _MAX_BARGE_UTTERANCE_MS:
            _LOG.info("voice.echo_shed", duration_ms=duration_ms)
            return
        task = asyncio.create_task(
            self._decode_and_publish(
                payload, sample_rate_hz, utterance_id, captured_while_speaking
            ),
            name=f"voice-decode[{utterance_id}]",
        )
        self._decode_tasks.add(task)
        task.add_done_callback(self._decode_tasks.discard)

    async def _decode_and_publish(
        self,
        payload: bytes,
        sample_rate_hz: int,
        utterance_id: UtteranceId,
        captured_while_speaking: bool,
    ) -> None:
        try:
            async with self._decode_lock:
                transcription = await self.asr.transcribe_batch(
                    payload,
                    sample_rate_hz=sample_rate_hz,
                    language_hint=self.config.language_hint,
                )
            named, stripped = self._match_wake_name(transcription.text)
            # Policy uses CAPTURE-time state: an echo of the robot's own voice
            # decoded after it finished speaking must not read as user speech.
            speaking = captured_while_speaking
            text = self._resolve_forward(
                transcription.text, named=named, stripped=stripped, speaking=speaking
            )
            _LOG.info(
                "voice.utterance",
                heard=transcription.text,
                forwarded=text,
                gated_out=text is None,
                named=named,
                robot_speaking=speaking,
            )
            if text is None:
                return
            if speaking and named and self.on_user_speech is not None:
                # The user called the robot by name over its own speech —
                # cut it off before answering.
                await self.on_user_speech()
            await self.bus.publish(
                AsrFinal(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.config.producer,
                    ),
                    session_id=self.session_id,
                    utterance_id=utterance_id,
                    text=text,
                    language=transcription.language,
                    confidence=transcription.confidence,
                )
            )
        except Exception:
            _LOG.exception("voice.decode_failed")

    def _resolve_forward(
        self, text: str, *, named: bool, stripped: str, speaking: bool
    ) -> str | None:
        """Apply the wake-name policy; returns the text to forward or None."""
        if not self.config.wake_name:
            return text
        if self.config.wake_name_mode == "interrupt_only":
            if speaking and not named:
                # Robot is talking: ignore anything not addressed to it —
                # this also keeps it from hearing its own speaker echo.
                return None
            return stripped if named else text
        # "always": only named utterances get through.
        return stripped if named else None

    def _match_wake_name(self, text: str) -> tuple[bool, str]:
        """Detect the wake name and strip it: (named, text-without-leading-name).

        Matches the wake name's stem exactly OR fuzzily against the first word
        (the ASR sometimes mangles the leading wake word); the fuzzy pass keeps
        near-misses like "слуги"/"слуга" working without letting arbitrary
        speech through.
        """
        name = self.config.wake_name
        if not name:
            return False, text
        stem = name.lower()[:4]
        lower = text.lower()
        matched = stem in lower
        if not matched:
            first = re.sub(r"^[\W_]+", "", lower).split(" ", 1)[0] if lower.strip() else ""
            if first and SequenceMatcher(None, first, name.lower()).ratio() >= _WAKE_FUZZY_RATIO:
                matched = True
        if not matched:
            return False, text
        stripped = re.sub(
            rf"^\s*\W*(?:{re.escape(stem)}\w*|\w+)\W*[\s,.!?:—-]*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        return True, (stripped.strip() or text)

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
    """Log-space mapping for probability [0, 1] to a decibel-like scalar.

    Only used for observability, not for gating.
    """
    if prob <= 0.0:
        return -120.0
    return 20.0 * math.log10(max(prob, 1e-6))
