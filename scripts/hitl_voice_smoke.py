"""Full voice-loop HITL smoke test against a live robot.

Runs on the target robot (not on developer laptops). Expects:

  - `nats-server` running and reachable at `HR_VOICE_NATS`.
  - `faster-whisper[runtime]` and `piper-tts[runtime]` installed on the host.
  - `silero-vad[runtime]` installed.
  - A wake-word ONNX model, if `HR_VOICE_WAKEWORD_MODEL` is set.
  - The mic + speaker cabled per ADR-0004 (XMOS XVF3800 preferred).

The script exits 0 on end-to-end success:

  1. Runner starts.
  2. Simulate an LLM answer by publishing a canned `LlmAnswer` into NATS.
  3. Watch for `tts.synth.finished` on the bus.
  4. Cleanly stop.

Usage
-----
    HR_VOICE_NATS=nats://127.0.0.1:4222 \
    HR_VOICE_PIPER_RU=/opt/piper/voices/ru_RU-ruslan-medium.onnx \
    HR_VOICE_AUDIO_IN=alsa \
    HR_VOICE_AUDIO_OUT=null \
    python scripts/hitl_voice_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass

from humanoid_robot.adapters.asr_whisper import FasterWhisperAsr, FasterWhisperConfig
from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.adapters.tts_piper import PiperConfig, PiperTts
from humanoid_robot.adapters.vad_silero import SileroConfig, SileroVad
from humanoid_robot.domain.knowledge import Citation
from humanoid_robot.domain.shared import new_correlation_id, new_session_id
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.events import LlmAnswer, TtsSynthesisFinished
from humanoid_robot.events.base import BaseEvent, EventMetadata
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.voice import VoiceRunner

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _NullAudioIn:
    async def close(self) -> None:
        return

    def stream(self) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            while True:
                await asyncio.sleep(0.05)
                yield AudioFrame(pcm=b"\x00\x00" * 800, format=_FMT, monotonic_ns=0)

        return _gen()


@dataclass(slots=True)
class _NullAudioOut:
    played_bytes: int = 0

    async def play(self, frame: AudioFrame) -> None:
        self.played_bytes += len(frame.pcm)

    async def flush(self) -> None:
        return

    async def stop(self) -> None:
        return


async def _main() -> int:
    nats_url = os.environ.get("HR_VOICE_NATS", "nats://127.0.0.1:4222")
    piper_ru = os.environ.get("HR_VOICE_PIPER_RU")
    if piper_ru is None:
        print("HR_VOICE_PIPER_RU must point at a Piper .onnx voice", file=sys.stderr)
        return 2

    session_id = new_session_id()
    bus = NatsEventBus(config=NatsEventBusConfig(servers=(nats_url,), name="hitl-voice"))
    await bus.connect()

    tts_done = asyncio.Event()

    async def _on_finished(ev: BaseEvent) -> None:
        if isinstance(ev, TtsSynthesisFinished):
            tts_done.set()

    await bus.subscribe(TtsSynthesisFinished.subject, _on_finished)

    runner = VoiceRunner(
        audio_in=_NullAudioIn(),
        audio_out=_NullAudioOut(),
        vad=SileroVad(SileroConfig()),
        asr=FasterWhisperAsr(FasterWhisperConfig()),
        tts=PiperTts(PiperConfig(voice_paths={"ru": piper_ru})),
        bus=bus,
        session_id=session_id,
    )

    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.5)  # let subscription attach

    await bus.publish(
        LlmAnswer(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="hitl-voice",
            ),
            session_id=session_id,
            text="Проверка голосового цикла на реальном роботе.",
            citations=(Citation(chunk_id="c1", quote="offline"),),
            confidence=0.9,
        )
    )

    try:
        await asyncio.wait_for(tts_done.wait(), timeout=30.0)
        print("hitl voice smoke: OK")
        return 0
    except TimeoutError:
        print("hitl voice smoke: TIMEOUT waiting for tts.synth.finished", file=sys.stderr)
        return 1
    finally:
        runner.request_stop()
        await task
        await bus.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
