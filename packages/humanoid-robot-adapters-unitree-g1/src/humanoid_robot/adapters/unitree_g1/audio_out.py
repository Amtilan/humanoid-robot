"""G1 speaker — `AudioOutPort` implementation on top of `AudioClient`.

The G1 head speaker consumes 16 kHz mono PCM16 chunks. Playback must be
wall-clock-paced (50 ms per chunk) to avoid starving the vendor audio
pipeline. This module keeps the pacing logic in one place so port callers
just `.play(frame)` with any frame size and the module converts.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.adapters.unitree_g1.sdk import SdkHandles
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_G1_SAMPLE_RATE = 16_000
_G1_CHANNELS = 1
_G1_SAMPLE_WIDTH_BYTES = 2
_CHUNK_MS = 50
_CHUNK_BYTES = _G1_SAMPLE_RATE * _G1_CHANNELS * _G1_SAMPLE_WIDTH_BYTES * _CHUNK_MS // 1000  # 1600
_G1_FORMAT = AudioFormat(
    sample_rate_hz=_G1_SAMPLE_RATE,
    channels=_G1_CHANNELS,
    sample_width_bytes=_G1_SAMPLE_WIDTH_BYTES,
)


class AudioFormatMismatchError(RuntimeError):
    """Caller pushed audio in a format the G1 speaker cannot consume."""


@dataclass(slots=True)
class UnitreeG1AudioOut:
    """Wraps the vendor `AudioClient` with pacing + format validation."""

    _sdk: SdkHandles
    volume_pct: int = 100
    app_name: str = "cortex"
    _client: Any = field(default=None, init=False)
    _initialised: bool = field(default=False, init=False)
    _stream_id: str = field(default="", init=False)
    _next_send_monotonic: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def _ensure_client(self) -> Any:
        if not self._initialised:
            client = self._sdk.audio_client.AudioClient()
            client.SetTimeout(10.0)
            client.Init()
            client.SetVolume(self.volume_pct)
            self._client = client
            self._stream_id = str(int(time.time() * 1000))
            self._next_send_monotonic = time.monotonic()
            self._initialised = True
        return self._client

    async def play(self, frame: AudioFrame) -> None:
        if frame.format != _G1_FORMAT:
            msg = (
                f"G1 speaker expects {_G1_FORMAT!r}, got {frame.format!r}. "
                f"Resample upstream before calling AudioOutPort.play()."
            )
            raise AudioFormatMismatchError(msg)
        pcm = frame.pcm
        async with self._lock:
            client = self._ensure_client()
            for offset in range(0, len(pcm), _CHUNK_BYTES):
                chunk = pcm[offset : offset + _CHUNK_BYTES]
                self._pace_wait_for_next_slot()
                client.PlayStream(self.app_name, self._stream_id, chunk)

    async def flush(self) -> None:
        # AudioClient does not expose a public flush; playback drains naturally
        # once the vendor buffer empties.
        return

    async def stop(self) -> None:
        async with self._lock:
            if not self._initialised:
                return
            self._client.PlayStop(self.app_name)
            self._next_send_monotonic = time.monotonic()

    def _pace_wait_for_next_slot(self) -> None:
        now = time.monotonic()
        # If we fell far behind (long silence), reset the clock so we don't
        # burst-play accumulated backlog on the next call.
        if self._next_send_monotonic < now - 0.5:
            self._next_send_monotonic = now
        else:
            time.sleep(max(0.0, self._next_send_monotonic - now))
        self._next_send_monotonic += _CHUNK_MS / 1000.0
