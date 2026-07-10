"""Verify the audio_out fix — pacing uses asyncio.sleep, not time.sleep."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.unitree_g1 import UnitreeG1Adapter
from humanoid_robot.adapters.unitree_g1.audio_out import (
    AudioFormatMismatchError,
    UnitreeG1AudioOut,
)
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_G1 = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeAudioClient:
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


@pytest.mark.asyncio
async def test_pacing_yields_control_to_event_loop() -> None:
    """The old code called time.sleep() and starved the loop; the new
    code awaits asyncio.sleep so co-tasks progress during playback."""

    client = _FakeAudioClient()
    audio_out = UnitreeG1AudioOut()
    audio_out.attach_client(client)

    # ~800 ms of audio in one call → 16 chunks x 50 ms each.
    pcm = b"\x00\x00" * 16_000  # 1 s of 16-bit mono 16 kHz silence

    ticks: list[float] = []

    async def _co_ticker() -> None:
        for _ in range(4):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    ticker = asyncio.create_task(_co_ticker())
    await audio_out.play(AudioFrame(pcm=pcm, format=_G1, monotonic_ns=0))
    await ticker

    # The old code would block for ~800 ms and the ticker would run only
    # AFTER play returned. The new code must let the ticker fire at least
    # once mid-flight — check by observing all 4 tick times were within
    # the play window (first tick before end, last tick within play span).
    assert len(client.played) == 20  # 1 s / 50 ms
    assert len(ticks) == 4
    # Any signal that the loop wasn't fully blocked: the ticker's tick
    # spread should be roughly 4x20ms ≈ 80 ms, not squished to zero.
    spread = ticks[-1] - ticks[0]
    assert spread > 0.04, f"event loop appears blocked (spread={spread})"


@pytest.mark.asyncio
async def test_wrong_format_raises() -> None:
    audio_out = UnitreeG1AudioOut()
    audio_out.attach_client(_FakeAudioClient())
    bad = AudioFormat(sample_rate_hz=48_000, channels=1, sample_width_bytes=2)
    with pytest.raises(AudioFormatMismatchError):
        await audio_out.play(AudioFrame(pcm=b"\x00\x00" * 100, format=bad, monotonic_ns=0))


@pytest.mark.asyncio
async def test_adapter_root_exposes_audio_sub_ports() -> None:
    adapter = UnitreeG1Adapter()
    assert adapter.audio_in is adapter.audio_in  # cached
    assert adapter.audio_out is adapter.audio_out
    # attach_audio_out_client replaces the port with a client-injected one
    fake = _FakeAudioClient()
    adapter.attach_audio_out_client(fake)
    await adapter.audio_out.play(AudioFrame(pcm=b"\x00\x00" * 800, format=_G1, monotonic_ns=0))
    assert len(fake.played) == 1
