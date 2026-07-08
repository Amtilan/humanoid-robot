"""UnitreeG1AudioIn tests using an injected fake socket."""

from __future__ import annotations

import contextlib
import socket
from dataclasses import dataclass, field

from humanoid_robot.adapters.unitree_g1.audio_in import (
    G1AudioInConfig,
    G1AudioInSocketFactory,
    UnitreeG1AudioIn,
)


@dataclass(slots=True)
class _FakeSocketFactory(G1AudioInSocketFactory):
    """Yields a pre-scripted sequence of UDP packets through a socketpair."""

    packets: list[bytes] = field(default_factory=list)
    writer: socket.socket | None = None
    reader: socket.socket | None = None

    def create(self, _config: G1AudioInConfig) -> socket.socket:
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        writer.setblocking(False)
        for pkt in self.packets:
            writer.send(pkt)
        self.reader = reader
        self.writer = writer
        return reader

    def cleanup(self) -> None:
        for sock in (self.reader, self.writer):
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()


class TestUnitreeG1AudioIn:
    async def test_mono_stream_passes_through_unchanged(self) -> None:
        packet = b"\x11\x22\x33\x44\x55\x66\x77\x88"
        factory = _FakeSocketFactory(packets=[packet])
        adapter = UnitreeG1AudioIn(
            config=G1AudioInConfig(input_channels=1),
            _socket_factory=factory,
        )
        frames = []
        stream = adapter.stream()
        try:
            async for frame in stream:
                frames.append(frame)
                if len(frames) == 1:
                    break
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        await adapter.close()
        factory.cleanup()
        assert frames[0].pcm == packet
        assert frames[0].format.channels == 1

    async def test_six_channel_downmix_picks_target_channel(self) -> None:
        # Two 6-channel frames of PCM16 samples: channel 0 has values 0x0100 and
        # 0x0200 respectively; other channels are 0.
        ch_samples = 6
        sw = 2
        frame_bytes = ch_samples * sw
        frame1 = bytearray(frame_bytes)
        frame1[0:sw] = b"\x00\x01"  # little-endian 0x0100 = 256
        frame2 = bytearray(frame_bytes)
        frame2[0:sw] = b"\x00\x02"  # 0x0200 = 512
        payload = bytes(frame1 + frame2)

        factory = _FakeSocketFactory(packets=[payload])
        adapter = UnitreeG1AudioIn(
            config=G1AudioInConfig(input_channels=6, downmix_channel=0),
            _socket_factory=factory,
        )
        frames = []
        stream = adapter.stream()
        try:
            async for frame in stream:
                frames.append(frame)
                if len(frames) == 1:
                    break
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        await adapter.close()
        factory.cleanup()
        assert frames[0].pcm == b"\x00\x01\x00\x02"
        assert frames[0].format.channels == 1

    async def test_close_is_idempotent(self) -> None:
        factory = _FakeSocketFactory(packets=[b"\x00\x01" * 4])
        adapter = UnitreeG1AudioIn(
            config=G1AudioInConfig(input_channels=1),
            _socket_factory=factory,
        )
        stream = adapter.stream()
        try:
            first = await anext(stream)
            assert first.pcm
        finally:
            await stream.aclose()  # type: ignore[attr-defined]
        # Cleanly close and confirm a second close is a no-op.
        await adapter.close()
        await adapter.close()
        factory.cleanup()
