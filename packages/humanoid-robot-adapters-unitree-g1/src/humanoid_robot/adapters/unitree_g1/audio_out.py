"""G1 speaker — `AudioOutPort` implementation on top of `AudioClient`.

The G1 head speaker consumes 16 kHz mono PCM16 chunks. Playback must be
wall-clock-paced (50 ms per chunk) to avoid starving the vendor audio
pipeline. This module keeps the pacing logic in one place so port callers
just `.play(frame)` with any frame size and the module converts.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from humanoid_robot.adapters.unitree_g1.sdk import (
    SdkHandles,
    UnitreeSdkNotAvailableError,
    require_sdk,
)
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
    """Wraps the vendor `AudioClient` with pacing + format validation.

    ``_sdk`` may be ``None``; in that case ``require_sdk()`` runs on the
    first ``play()`` call.  ``attach_client()`` is a test hook that lets
    callers plug a fake AudioClient without touching the vendor loader.
    """

    _sdk: SdkHandles | None = None
    volume_pct: int = 100
    app_name: str = "cortex"
    _client: Any = field(default=None)
    _initialised: bool = field(default=False)
    _stream_id: str = field(default="")
    _next_send_monotonic: float = field(default=0.0)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def attach_client(self, client: Any) -> None:
        """Test hook: inject a fake AudioClient (skips vendor SDK)."""
        self._client = client
        self._sdk = SdkHandles(channel=None, audio_client=None, arm_client=None)
        self._stream_id = "test-stream"
        self._next_send_monotonic = time.monotonic()
        self._initialised = True

    def _ensure_client(self) -> Any:
        if self._initialised:
            return self._client
        sdk = self._sdk
        if sdk is None:
            sdk = require_sdk()
            self._sdk = sdk
        client = sdk.audio_client.AudioClient()
        _try_call(client, "SetTimeout", 10.0)
        _try_call(client, "Init")
        _try_call(client, "SetVolume", self.volume_pct)
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
            try:
                client = self._ensure_client()
            except UnitreeSdkNotAvailableError as exc:
                raise AudioFormatMismatchError(f"SDK unavailable: {exc}") from exc
            for offset in range(0, len(pcm), _CHUNK_BYTES):
                chunk = pcm[offset : offset + _CHUNK_BYTES]
                await self._pace_wait_for_next_slot()
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

    async def _pace_wait_for_next_slot(self) -> None:
        now = time.monotonic()
        # If we fell far behind (long silence), reset the clock so we don't
        # burst-play accumulated backlog on the next call.
        if self._next_send_monotonic < now - 0.5:
            self._next_send_monotonic = now
        else:
            wait = self._next_send_monotonic - now
            if wait > 0:
                await asyncio.sleep(wait)
        self._next_send_monotonic += _CHUNK_MS / 1000.0


def _try_call(client: Any, name: str, *args: object) -> None:
    fn = getattr(client, name, None)
    if callable(fn):
        with contextlib.suppress(Exception):
            fn(*args)
