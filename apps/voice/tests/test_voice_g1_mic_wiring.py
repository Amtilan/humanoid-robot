"""End-to-end: UnitreeG1AudioIn (fake socket) → VoiceSession → asr.final.

Uses a Unix ``socket.socketpair()`` to feed synthetic multicast packets
into the real G1 audio-in port; the session drives VAD → ASR with
scripted fakes and the test asserts a properly-shaped ``asr.final``
lands on the bus.  This is the mirror image of R7 (which exercised
the llm.answer → G1 audio_out path).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from humanoid_robot.adapters.unitree_g1.audio_in import (
    G1AudioInConfig,
    UnitreeG1AudioIn,
)
from humanoid_robot.domain.shared import new_session_id
from humanoid_robot.domain.voice import Language, Transcription
from humanoid_robot.events import AsrFinal, SpeechDetected
from humanoid_robot.ports.ai import AsrStreamChunk
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.ports.voice import VadDecision
from humanoid_robot.testing import InMemoryEventBus
from humanoid_robot.voice.session import VoiceSession, VoiceSessionConfig


class _ScriptedSocketFactory:
    """Returns a socket half of a ``socketpair`` pre-loaded with packets."""

    def __init__(self, packets: list[bytes]) -> None:
        self._packets = packets
        self._client: socket.socket | None = None

    def create(self, _config: G1AudioInConfig) -> socket.socket:
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        server.setblocking(False)
        for packet in self._packets:
            client.sendall(packet)
        client.shutdown(socket.SHUT_WR)
        # Close the write end so reads on the server side see EOF once the
        # queued bytes drain.
        client.close()
        self._client = None
        return server


@dataclass(slots=True)
class _FakeVad:
    scripted: list[bool]
    _index: int = 0

    async def decide(self, _f: AudioFrame) -> VadDecision:
        is_speech = self.scripted[self._index]
        self._index = min(self._index + 1, len(self.scripted) - 1)
        return VadDecision(is_speech=is_speech, speech_probability=0.9 if is_speech else 0.05)

    async def reset(self) -> None:
        self._index = 0


@dataclass(slots=True)
class _FakeAsr:
    transcript: str
    seen_pcm: bytes = b""

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        del sample_rate_hz, language_hint
        self.seen_pcm = pcm
        return Transcription(text=self.transcript, language=Language.RU, confidence=0.92)

    def transcribe_stream(  # pragma: no cover
        self,
        _frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        del language_hint
        raise NotImplementedError


@pytest.mark.asyncio
async def test_g1_mono_stream_reaches_asr_final() -> None:
    # One 320-byte packet = 160 samples of 16-bit mono at 16 kHz = 10 ms.
    # Send 40 speech packets (400 ms) + 60 silence packets (600 ms) = 1 s.
    packet_samples = 160
    packet_bytes_mono = packet_samples * 2
    speech_packet = b"\x11\x11" * packet_samples
    silence_packet = b"\x00\x00" * packet_samples
    packets = [speech_packet] * 40 + [silence_packet] * 60

    bus = InMemoryEventBus()
    audio_in = UnitreeG1AudioIn(
        config=G1AudioInConfig(input_channels=1),
        _socket_factory=_ScriptedSocketFactory(packets),
    )
    vad = _FakeVad(scripted=[True] * 40 + [False] * 60)
    asr = _FakeAsr(transcript="привет робот")

    session_id = new_session_id()
    session = VoiceSession(
        vad=vad,
        asr=asr,
        bus=bus,
        config=VoiceSessionConfig(min_speech_ms=150, silence_hang_ms=300),
        session_id=session_id,
    )

    await asyncio.wait_for(session.run(audio_in.stream()), timeout=5.0)
    await audio_in.close()

    finals = [ev for ev in bus.published if isinstance(ev, AsrFinal)]
    assert len(finals) == 1
    assert finals[0].text == "привет робот"
    assert finals[0].session_id == session_id
    assert asr.seen_pcm.startswith(speech_packet)  # buffered from real frames
    # SpeechDetected fires at the leading edge.
    detected = [ev for ev in bus.published if isinstance(ev, SpeechDetected)]
    assert len(detected) == 1
    # PCM length should be a multiple of frame size (no torn samples).
    assert len(asr.seen_pcm) % packet_bytes_mono == 0


@pytest.mark.asyncio
async def test_g1_downmix_from_six_channels_produces_valid_frames() -> None:
    """Regression: the 6-ch far-field mix must be downmixed to mono."""
    packet_samples = 160
    per_channel_bytes = 2  # PCM16
    # A packet with 6 channels — non-zero on the target channel (0),
    # noise on the others so we can prove the downmix picked ch 0.
    frame_bytes = 6 * per_channel_bytes
    packet = bytearray()
    for _ in range(packet_samples):
        packet.extend(b"\xab\xcd")  # ch 0
        packet.extend(b"\x00\x00" * 5)  # ch 1..5 zeroed
    packet_bytes = bytes(packet)
    assert len(packet_bytes) == packet_samples * frame_bytes

    bus = InMemoryEventBus()
    audio_in = UnitreeG1AudioIn(
        config=G1AudioInConfig(input_channels=6, downmix_channel=0),
        _socket_factory=_ScriptedSocketFactory([packet_bytes] * 30),
    )
    vad = _FakeVad(scripted=[True] * 15 + [False] * 15)
    asr = _FakeAsr(transcript="да")

    session = VoiceSession(
        vad=vad,
        asr=asr,
        bus=bus,
        config=VoiceSessionConfig(min_speech_ms=100, silence_hang_ms=100),
    )

    await asyncio.wait_for(session.run(audio_in.stream()), timeout=5.0)
    await audio_in.close()

    finals = [ev for ev in bus.published if isinstance(ev, AsrFinal)]
    assert len(finals) == 1
    # After downmix, each PCM16 sample is 2 bytes; the pattern from ch 0
    # ("\xAB\xCD") should appear repeatedly and NO "\x00\x00" tail.
    assert b"\xab\xcd\xab\xcd" in asr.seen_pcm
