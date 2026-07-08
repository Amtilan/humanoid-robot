"""UnitreeG1AudioOut tests with an injected fake SDK — no vendor deps."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from humanoid_robot.adapters.unitree_g1.audio_out import (
    AudioFormatMismatchError,
    UnitreeG1AudioOut,
)
from humanoid_robot.adapters.unitree_g1.sdk import SdkHandles
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_G1_FORMAT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)
_WRONG_FORMAT = AudioFormat(sample_rate_hz=48_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeAudioClient:
    chunks: list[bytes] = field(default_factory=list)
    volume_set: int | None = None
    play_stopped: bool = False
    init_calls: int = 0

    def SetTimeout(self, t: float) -> None:
        del t

    def Init(self) -> None:
        self.init_calls += 1

    def SetVolume(self, v: int) -> None:
        self.volume_set = v

    def PlayStream(self, app_name: str, stream_id: str, chunk: bytes) -> None:
        del app_name, stream_id
        self.chunks.append(chunk)

    def PlayStop(self, app_name: str) -> None:
        del app_name
        self.play_stopped = True


def _mk_handles() -> tuple[SdkHandles, _FakeAudioClient]:
    fake = _FakeAudioClient()
    audio_module = SimpleNamespace(AudioClient=lambda: fake)
    handles = SdkHandles(
        channel=SimpleNamespace(),
        audio_client=audio_module,
        arm_client=SimpleNamespace(),
        loco_client=None,
    )
    return handles, fake


def _frame(size: int, fmt: AudioFormat = _G1_FORMAT) -> AudioFrame:
    return AudioFrame(pcm=b"\x00" * size, format=fmt, monotonic_ns=0)


class TestUnitreeG1AudioOut:
    async def test_rejects_wrong_format(self) -> None:
        handles, _ = _mk_handles()
        out = UnitreeG1AudioOut(_sdk=handles)
        with pytest.raises(AudioFormatMismatchError):
            await out.play(_frame(1600, fmt=_WRONG_FORMAT))

    async def test_chunk_size_is_1600_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handles, fake = _mk_handles()
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        out = UnitreeG1AudioOut(_sdk=handles)
        # 3200 bytes = two 50 ms chunks.
        await out.play(_frame(3200))
        assert [len(c) for c in fake.chunks] == [1600, 1600]

    async def test_short_final_chunk_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handles, fake = _mk_handles()
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        out = UnitreeG1AudioOut(_sdk=handles)
        await out.play(_frame(2400))  # 1600 + 800
        assert [len(c) for c in fake.chunks] == [1600, 800]

    async def test_volume_set_on_init(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handles, fake = _mk_handles()
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        out = UnitreeG1AudioOut(_sdk=handles, volume_pct=42)
        await out.play(_frame(1600))
        assert fake.volume_set == 42
        assert fake.init_calls == 1

    async def test_stop_calls_play_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handles, fake = _mk_handles()
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        out = UnitreeG1AudioOut(_sdk=handles)
        await out.play(_frame(1600))
        await out.stop()
        assert fake.play_stopped

    async def test_stop_before_play_noop(self) -> None:
        handles, fake = _mk_handles()
        out = UnitreeG1AudioOut(_sdk=handles)
        await out.stop()
        assert not fake.play_stopped
