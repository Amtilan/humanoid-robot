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
import warnings
from dataclasses import dataclass, field
from typing import Any

# audioop is stdlib on 3.12 (removed in 3.13; add the `audioop-lts` shim
# then). Importing it emits a DeprecationWarning that the test suite treats
# as an error, so silence just this import.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

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
# Lead buffer primed at the start of an utterance: the first ~200 ms of chunks
# are sent back-to-back to fill the vendor speaker's buffer before pacing
# engages, so asyncio scheduling jitter can't underrun it mid-word. Must stay
# under the 0.5 s idle-reset threshold in `_pace_wait_for_next_slot`.
_LEAD_S = 0.2
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
    network_interface: str | None = None
    _client: Any = field(default=None)
    _initialised: bool = field(default=False)
    _channel_initialised: bool = field(default=False)
    _stream_id: str = field(default="")
    _next_send_monotonic: float = field(default=0.0)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # audioop.ratecv filter state, carried across frames of one utterance so
    # resampling stays continuous (no per-frame clicks). Reset on stop().
    _resample_state: Any = field(default=None)
    _resample_src_rate: int = field(default=0)

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
        # DDS ChannelFactory is a process-global side effect; initialise it
        # on first play() so entry-point-driven runners don't crash off-robot.
        if not self._channel_initialised and self.network_interface and sdk.channel is not None:
            init = getattr(sdk.channel, "ChannelFactoryInitialize", None)
            if callable(init):
                init(0, self.network_interface)
            self._channel_initialised = True
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
        pcm = self._to_g1_pcm(frame)
        async with self._lock:
            try:
                client = self._ensure_client()
            except UnitreeSdkNotAvailableError as exc:
                raise AudioFormatMismatchError(f"SDK unavailable: {exc}") from exc
            # At the start of an utterance (not mid-stream) put the send clock
            # slightly in the past so the first _LEAD_S of chunks flush without
            # waiting, priming the vendor buffer before realtime pacing kicks in.
            now = time.monotonic()
            if self._next_send_monotonic <= now:
                self._next_send_monotonic = now - _LEAD_S
            for offset in range(0, len(pcm), _CHUNK_BYTES):
                chunk = pcm[offset : offset + _CHUNK_BYTES]
                await self._pace_wait_for_next_slot()
                # Vendor DDS RPC — run off-loop so a hung call can't freeze the
                # whole process (the vendor SDK is known to wedge occasionally).
                await asyncio.to_thread(client.PlayStream, self.app_name, self._stream_id, chunk)

    def _to_g1_pcm(self, frame: AudioFrame) -> bytes:
        """Coerce a frame to the G1's 16 kHz mono PCM16. Sample-rate
        differences (e.g. piper's 22050 Hz) are resampled; channel/width
        differences we refuse rather than guess at."""
        fmt = frame.format
        if fmt == _G1_FORMAT:
            return frame.pcm
        if fmt.channels != _G1_CHANNELS or fmt.sample_width_bytes != _G1_SAMPLE_WIDTH_BYTES:
            msg = (
                f"G1 speaker needs mono 16-bit PCM; got {fmt!r}. Only the "
                f"sample rate is auto-resampled."
            )
            raise AudioFormatMismatchError(msg)
        if fmt.sample_rate_hz != self._resample_src_rate:
            # New source rate (new utterance/voice) — restart the filter.
            self._resample_state = None
            self._resample_src_rate = fmt.sample_rate_hz
        converted, self._resample_state = audioop.ratecv(
            frame.pcm,
            _G1_SAMPLE_WIDTH_BYTES,
            _G1_CHANNELS,
            fmt.sample_rate_hz,
            _G1_SAMPLE_RATE,
            self._resample_state,
        )
        return converted

    async def flush(self) -> None:
        # AudioClient does not expose a public flush; playback drains naturally
        # once the vendor buffer empties.
        return

    async def stop(self) -> None:
        async with self._lock:
            self._resample_state = None
            self._resample_src_rate = 0
            if not self._initialised:
                return
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    asyncio.to_thread(self._client.PlayStop, self.app_name), timeout=5.0
                )
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
