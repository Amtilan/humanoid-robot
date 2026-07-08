"""G1 microphone — ``AudioInPort`` implementation.

The G1 head microphone array multicasts raw audio to a UDP class-D
(multicast) group; the default group and port are documented as constants
below.  Payload is a 16 kHz mono PCM16 stream; some firmwares emit a
6-channel far-field mix that we downmix to mono here (channel 0 tends to
be the beamformed centre).

The port yields ``AudioFrame`` objects.  The socket is opened lazily on
first ``stream()`` iteration; if that fails, the exception surfaces to
the caller so the runner can escalate.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import struct
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_DEFAULT_GROUP = "239.168.123.161"  # pragma: allowlist secret
_DEFAULT_PORT = 5555
_DEFAULT_LOCAL_IP = "0.0.0.0"  # noqa: S104  # pragma: allowlist secret
_DEFAULT_RECV_BUFFER_BYTES = 4096
_DEFAULT_SAMPLE_RATE_HZ = 16_000
_DEFAULT_CHANNELS = 1
_DEFAULT_INPUT_CHANNELS = 6
_DEFAULT_SAMPLE_WIDTH_BYTES = 2
_MONO_FORMAT = AudioFormat(
    sample_rate_hz=_DEFAULT_SAMPLE_RATE_HZ,
    channels=_DEFAULT_CHANNELS,
    sample_width_bytes=_DEFAULT_SAMPLE_WIDTH_BYTES,
)


class G1AudioInConfig(BaseModel):
    """G1 multicast mic config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    multicast_group: str = _DEFAULT_GROUP
    multicast_port: int = Field(default=_DEFAULT_PORT, ge=1, le=65_535)
    local_ip: str = _DEFAULT_LOCAL_IP
    interface_ip: str | None = None  # optional bind-to-interface for IGMP
    input_channels: int = Field(default=_DEFAULT_INPUT_CHANNELS, ge=1, le=16)
    downmix_channel: int = Field(default=0, ge=0, le=15)
    recv_buffer_bytes: int = Field(default=_DEFAULT_RECV_BUFFER_BYTES, ge=64, le=65_507)


class G1AudioInSocketFactory:
    """Creates the multicast socket. Overridable for tests."""

    def create(self, config: G1AudioInConfig) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((config.local_ip, config.multicast_port))
        mreq = struct.pack(
            "=4s4s",
            socket.inet_aton(config.multicast_group),
            socket.inet_aton(config.interface_ip or config.local_ip),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)
        return sock


@dataclass(slots=True)
class UnitreeG1AudioIn:
    """AudioInPort backed by the G1 mic multicast stream."""

    config: G1AudioInConfig = field(default_factory=G1AudioInConfig)
    _socket_factory: G1AudioInSocketFactory = field(default_factory=G1AudioInSocketFactory)
    _socket: socket.socket | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    def stream(self) -> AsyncIterator[AudioFrame]:
        """Yield `AudioFrame`s as multicast packets arrive."""

        async def _gen() -> AsyncIterator[AudioFrame]:
            loop = asyncio.get_running_loop()
            sock = self._ensure_socket()
            while not self._closed:
                try:
                    data = await loop.sock_recv(sock, self.config.recv_buffer_bytes)
                except (BlockingIOError, InterruptedError):
                    await asyncio.sleep(0.005)
                    continue
                if not data:
                    return
                pcm = self._downmix(data)
                if not pcm:
                    continue
                yield AudioFrame(pcm=pcm, format=_MONO_FORMAT, monotonic_ns=time.monotonic_ns())

        return _gen()

    async def close(self) -> None:
        self._closed = True
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
            self._socket = None

    def _ensure_socket(self) -> socket.socket:
        if self._socket is None:
            self._socket = self._socket_factory.create(self.config)
        return self._socket

    def _downmix(self, payload: bytes) -> bytes:
        ch = self.config.input_channels
        if ch == 1:
            return payload
        frame_bytes = ch * _DEFAULT_SAMPLE_WIDTH_BYTES
        # Drop any tail that doesn't cover a full multi-channel frame.
        usable_len = (len(payload) // frame_bytes) * frame_bytes
        if usable_len == 0:
            return b""
        buf = memoryview(payload)[:usable_len]
        target = self.config.downmix_channel
        # Fast path: copy the target channel's PCM16 samples out.
        out = bytearray(usable_len // ch)
        for i in range(0, usable_len, frame_bytes):
            offset = i + target * _DEFAULT_SAMPLE_WIDTH_BYTES
            out_offset = (i // frame_bytes) * _DEFAULT_SAMPLE_WIDTH_BYTES
            out[out_offset : out_offset + _DEFAULT_SAMPLE_WIDTH_BYTES] = buf[
                offset : offset + _DEFAULT_SAMPLE_WIDTH_BYTES
            ]
        return bytes(out)
