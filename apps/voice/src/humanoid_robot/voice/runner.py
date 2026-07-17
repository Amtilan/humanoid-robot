"""VoiceRunner — full input+output composition.

Ties together:
    - `AudioInPort` (mic stream)
    - `VadPort` (voice activity)
    - `WakeWordPort` (optional wake gate)
    - `AsrPort` (transcription)
    - `TtsPort` (synthesis)
    - `AudioOutPort` (speaker)
    - `EventBusPort` (NATS)

Runs until `.request_stop()` is called or the mic stream ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from humanoid_robot.domain.shared import SessionId, new_session_id
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    AsrPort,
    AudioFrame,
    AudioInPort,
    AudioOutPort,
    EventBusPort,
    Subscription,
    TtsPort,
    VadPort,
    WakeWordPort,
)
from humanoid_robot.voice.session import VoiceSession, VoiceSessionConfig
from humanoid_robot.voice.tts_speaker import TtsSpeaker

_LOG = get_logger("cortex-voice.runner")


@dataclass(slots=True)
class VoiceRunner:
    """Composes input + output sides into one long-running process."""

    audio_in: AudioInPort
    audio_out: AudioOutPort
    vad: VadPort
    asr: AsrPort
    tts: TtsPort
    bus: EventBusPort
    wake_word: WakeWordPort | None = None
    config: VoiceSessionConfig = field(default_factory=VoiceSessionConfig)
    session_id: SessionId = field(default_factory=new_session_id)
    speak_all: bool = False
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _tts_sub: Subscription | None = None

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        session = VoiceSession(
            vad=self.vad,
            asr=self.asr,
            bus=self.bus,
            wake_word=self.wake_word,
            config=self.config,
            session_id=self.session_id,
        )
        speaker = TtsSpeaker(
            tts=self.tts,
            audio_out=self.audio_out,
            bus=self.bus,
            session_id=self.session_id,
            producer=self.config.producer,
            speak_all=self.speak_all,
        )
        self._tts_sub = await speaker.start()
        _LOG.info("voice_runner.ready", session_id=self.session_id)

        session_task = asyncio.create_task(session.run(self._mic_stream()), name="voice-session")
        # We wait for a stop signal, not for the session to end. Even after
        # the mic stream drains, TTS replies to previously-emitted asr.final
        # events may still be arriving; only an explicit stop tears the
        # runner down.
        try:
            await self._stop.wait()
        finally:
            if not session_task.done():
                session_task.cancel()
            try:
                await session_task
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOG.exception("voice_session task exited with error")
            if self._tts_sub is not None:
                await self._tts_sub.cancel()
            await self.audio_in.close()

    async def _mic_stream(self) -> AsyncIterator[AudioFrame]:
        async for frame in self.audio_in.stream():
            if self._stop.is_set():
                return
            yield frame
