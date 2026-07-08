"""Null audio adapters tests."""

from __future__ import annotations

import asyncio
from importlib.metadata import entry_points

from humanoid_robot.adapters.audio_null import (
    NullAudioIn,
    NullAudioInConfig,
    NullAudioOut,
    build_null_audio_in,
    build_null_audio_out,
)
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame


class TestNullAudioIn:
    async def test_yields_silent_frames_at_configured_size(self) -> None:
        adapter = NullAudioIn(
            config=NullAudioInConfig(sample_rate_hz=16_000, channels=1, frame_ms=10)
        )
        stream = adapter.stream()
        try:
            frames = []
            for _ in range(3):
                frame = await asyncio.wait_for(anext(stream), timeout=0.5)
                frames.append(frame)
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        await adapter.close()
        # 16 kHz * 1 ch * 2 B/s * 10 ms = 320 B.
        assert all(len(f.pcm) == 320 for f in frames)
        assert all(f.pcm == b"\x00" * 320 for f in frames)


class TestNullAudioOut:
    async def test_counts_played_bytes(self) -> None:
        out = NullAudioOut()
        fmt = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)
        await out.play(AudioFrame(pcm=b"\x00" * 1600, format=fmt, monotonic_ns=0))
        await out.play(AudioFrame(pcm=b"\x00" * 800, format=fmt, monotonic_ns=0))
        assert out.played_bytes == 2400
        # stop/flush are no-ops.
        await out.flush()
        await out.stop()


class TestFactories:
    def test_build_null_audio_in_accepts_kwargs(self) -> None:
        port = build_null_audio_in(sample_rate_hz=48_000, channels=2, frame_ms=20)
        assert port.config.sample_rate_hz == 48_000
        assert port.config.channels == 2

    def test_build_null_audio_out(self) -> None:
        port = build_null_audio_out()
        assert isinstance(port, NullAudioOut)

    def test_registered_under_both_audio_groups(self) -> None:
        in_names = {ep.name for ep in entry_points(group="humanoid_robot.audio_in_adapters")}
        out_names = {ep.name for ep in entry_points(group="humanoid_robot.audio_out_adapters")}
        assert "null" in in_names
        assert "null" in out_names
