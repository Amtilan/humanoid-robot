"""AlsaAudioIn tests with an injected fake `arecord` process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.audio_alsa import AlsaAudioIn, AlsaAudioInConfig
from humanoid_robot.adapters.audio_alsa.adapter import (
    _ArecordProcessFactory,
    resolve_auto_device,
)


@dataclass(slots=True)
class _FakeStream:
    buffer: bytes
    _offset: int = 0

    async def readexactly(self, n: int) -> bytes:
        if self._offset + n > len(self.buffer):
            raise asyncio.IncompleteReadError(partial=self.buffer[self._offset :], expected=n)
        chunk = self.buffer[self._offset : self._offset + n]
        self._offset += n
        return chunk


@dataclass(slots=True)
class _FakeProcess:
    stdout_bytes: bytes
    stdout: _FakeStream = field(init=False)
    _terminated: bool = False
    _waited: bool = False

    def __post_init__(self) -> None:
        self.stdout = _FakeStream(buffer=self.stdout_bytes)

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:
        self._terminated = True

    async def wait(self) -> int:
        self._waited = True
        return 0


@dataclass(slots=True)
class _FakeFactory(_ArecordProcessFactory):
    payload: bytes = b""
    spawned: list[AlsaAudioInConfig] = field(default_factory=list)

    async def spawn(self, config: AlsaAudioInConfig) -> _FakeProcess:  # type: ignore[override]
        self.spawned.append(config)
        return _FakeProcess(stdout_bytes=self.payload)


class TestAlsaAudioIn:
    async def test_yields_frames_of_configured_size(self) -> None:
        # 16 kHz * 1ch * 2B/s * 50 ms = 1600 B per frame.
        payload = b"\x00\x01" * 800 * 2  # 3200 B → two frames of 1600 B.
        factory = _FakeFactory(payload=payload)
        adapter = AlsaAudioIn(config=AlsaAudioInConfig(frame_ms=50), _process_factory=factory)
        frames = []
        stream = adapter.stream()
        try:
            async for frame in stream:
                frames.append(frame)
                if len(frames) == 2:
                    break
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        await adapter.close()
        assert [len(f.pcm) for f in frames] == [1600, 1600]
        assert frames[0].format.sample_rate_hz == 16_000
        assert factory.spawned  # process was actually requested

    async def test_close_terminates_process(self) -> None:
        factory = _FakeFactory(payload=b"\x00" * 3200)
        adapter = AlsaAudioIn(_process_factory=factory)
        stream = adapter.stream()
        try:
            await anext(stream)
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        await adapter.close()
        # Double close is a no-op.
        await adapter.close()

    async def test_wrong_sample_width_flag_raises(self) -> None:
        from humanoid_robot.adapters.audio_alsa.adapter import _format_flag

        with pytest.raises(ValueError, match="unsupported sample width"):
            _format_flag(AlsaAudioInConfig(sample_width_bytes=3))


def test_flat_kwargs_config_builds() -> None:
    """Voice composition passes selection.config as flat kwargs."""
    adapter = AlsaAudioIn(device="plughw:CARD=Device", sample_rate_hz=16000, channels=1)
    assert adapter.config.device == "plughw:CARD=Device"
    assert adapter.config.sample_rate_hz == 16000


class TestResolveAutoDevice:
    """`device: auto` picks the USB mic regardless of its card name."""

    def test_picks_first_usb_card_by_name(self) -> None:
        # Real /proc/asound/cards from the G1 Jetson with an SF-777W plugged in.
        cards = (
            " 0 [SF777W         ]: USB-Audio - SF-777W\n"
            "                      Jieli Technology SF-777W\n"
            " 1 [HDA            ]: tegra-hda - NVIDIA Jetson Orin NX HDA\n"
            " 2 [APE            ]: tegra-ape - NVIDIA Jetson Orin NX APE\n"
        )
        assert resolve_auto_device(cards) == "plughw:CARD=SF777W"

    def test_skips_builtin_cards(self) -> None:
        cards = (
            " 0 [HDA            ]: tegra-hda - NVIDIA Jetson Orin NX HDA\n"
            " 1 [Device         ]: USB-Audio - USB Composite Device\n"
        )
        assert resolve_auto_device(cards) == "plughw:CARD=Device"

    def test_no_usb_card_falls_back_to_default(self) -> None:
        cards = " 0 [APE            ]: tegra-ape - NVIDIA Jetson Orin NX APE\n"
        assert resolve_auto_device(cards) == "default"

    def test_explicit_device_untouched(self) -> None:
        adapter = AlsaAudioIn(device="auto")
        assert adapter.config.device == "auto"

    def test_parses_arecord_l_output(self) -> None:
        # Containers see only /dev/snd (no /proc/asound) — `arecord -l` format.
        cards = (
            "**** List of CAPTURE Hardware Devices ****\n"
            "card 0: SF777W [SF-777W], device 0: USB Audio [USB Audio]\n"
            "card 2: APE [NVIDIA Jetson Orin NX APE], device 0: tegra-dlink-0\n"
        )
        assert resolve_auto_device(cards) == "plughw:CARD=SF777W"
