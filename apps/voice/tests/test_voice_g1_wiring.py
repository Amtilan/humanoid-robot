"""End-to-end: llm.answer → TtsSpeaker → G1 audio_out (fake AudioClient)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from humanoid_robot.adapters.unitree_g1.audio_out import UnitreeG1AudioOut
from humanoid_robot.adapters.unitree_g1.factories import unitree_g1_audio_out
from humanoid_robot.domain.shared import new_correlation_id, new_session_id
from humanoid_robot.domain.voice import AudioFormat, Language
from humanoid_robot.events import LlmAnswer, TtsSynthesisFinished, TtsSynthesisStarted
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.ports import TtsRequest
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.testing import InMemoryEventBus
from humanoid_robot.voice.tts_speaker import TtsSpeaker

_G1_FORMAT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeAudioClient:
    """Records every PCM chunk the AudioOutPort forwards to the vendor SDK."""

    played: list[bytes] = field(default_factory=list)

    def SetTimeout(self, _t: float) -> None:  # noqa: N802
        return None

    def Init(self) -> None:  # noqa: N802
        return None

    def SetVolume(self, _v: int) -> None:  # noqa: N802
        return None

    def PlayStream(self, _app: str, _stream: str, chunk: bytes) -> None:  # noqa: N802
        self.played.append(chunk)

    def PlayStop(self, _app: str) -> None:  # noqa: N802
        return None


class _ScriptedTts:
    """Emits one 1 s frame per synthesize call."""

    def __init__(self) -> None:
        self.calls: list[TtsRequest] = []

    def _frame(self) -> AudioFrame:
        # ~1 s of silence at 16 kHz mono 16-bit
        return AudioFrame(pcm=b"\x00\x00" * 16_000, format=_G1_FORMAT, monotonic_ns=0)

    def synthesize_stream(self, req: TtsRequest) -> AsyncIterator[AudioFrame]:
        self.calls.append(req)
        frame = self._frame()

        async def _gen() -> AsyncIterator[AudioFrame]:
            yield frame

        return _gen()

    async def synthesize(self, req: TtsRequest) -> AudioFrame:
        self.calls.append(req)
        return self._frame()


def _llm_answer(session_id: Any, text: str = "Всё готово.") -> LlmAnswer:
    return LlmAnswer(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=session_id,
        text=text,
        language=Language.RU,
        citations=(),
        confidence=0.9,
    )


class TestFactoryIsLazy:
    def test_audio_out_factory_does_not_load_sdk(self) -> None:
        # Off-robot the vendor SDK is unimportable; the factory must
        # NOT raise UnitreeSdkNotAvailableError at construction.
        audio_out = unitree_g1_audio_out(
            network_interface="eth10", volume_pct=80, app_name="cortex-test"
        )
        assert isinstance(audio_out, UnitreeG1AudioOut)
        assert audio_out.network_interface == "eth10"
        assert audio_out.volume_pct == 80


class TestSpeakerWiring:
    @pytest.mark.asyncio
    async def test_llm_answer_flows_into_g1_audio_out(self) -> None:
        bus = InMemoryEventBus()
        session_id = new_session_id()
        fake_client = _FakeAudioClient()

        audio_out = UnitreeG1AudioOut()
        audio_out.attach_client(fake_client)

        speaker = TtsSpeaker(
            tts=_ScriptedTts(),
            audio_out=audio_out,
            bus=bus,
            session_id=session_id,
        )
        sub = await speaker.start()
        try:
            await bus.publish(_llm_answer(session_id))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if any(isinstance(ev, TtsSynthesisFinished) for ev in bus.published):
                    break

            started = [ev for ev in bus.published if isinstance(ev, TtsSynthesisStarted)]
            finished = [ev for ev in bus.published if isinstance(ev, TtsSynthesisFinished)]
            assert len(started) == 1
            assert len(finished) == 1
            assert finished[0].duration_ms >= 950  # ~1 s
            # 1 s / 50 ms pacing = 20 chunks
            assert len(fake_client.played) == 20
        finally:
            await sub.cancel()

    @pytest.mark.asyncio
    async def test_speaker_ignores_other_sessions(self) -> None:
        bus = InMemoryEventBus()
        session_id = new_session_id()
        other_session = new_session_id()
        fake_client = _FakeAudioClient()

        audio_out = UnitreeG1AudioOut()
        audio_out.attach_client(fake_client)
        speaker = TtsSpeaker(
            tts=_ScriptedTts(),
            audio_out=audio_out,
            bus=bus,
            session_id=session_id,
        )
        sub = await speaker.start()
        try:
            await bus.publish(_llm_answer(other_session))
            await asyncio.sleep(0.05)
            assert not any(isinstance(ev, TtsSynthesisStarted) for ev in bus.published)
            assert fake_client.played == []
        finally:
            await sub.cancel()
