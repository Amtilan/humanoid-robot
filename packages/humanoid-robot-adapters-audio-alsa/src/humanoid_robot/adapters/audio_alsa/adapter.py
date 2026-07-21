"""AudioInPort backed by an ``arecord`` subprocess.

The subprocess emits raw PCM on stdout at a fixed rate/width/channels;
`AlsaAudioIn` reads it in frame-sized chunks and yields `AudioFrame`s.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame


class AlsaRuntimeNotAvailableError(RuntimeError):
    """Raised when `arecord` is not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "arecord not found on PATH. Install ALSA utilities on the host: "
            "sudo apt install alsa-utils"
        )


class AlsaAudioInConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: str = "default"
    sample_rate_hz: int = Field(default=16_000, gt=0, le=192_000)
    channels: int = Field(default=1, ge=1, le=8)
    sample_width_bytes: int = Field(default=2, ge=1, le=4)
    frame_ms: int = Field(default=50, ge=10, le=200)
    arecord_path: str = "arecord"


# Factory type — accepts the argv list, returns a running process object with
# `stdout` (readable) and `terminate/wait` methods. Overridable for tests.
_ArecordProcess = asyncio.subprocess.Process

# Capture queue depth: 2 s of 50 ms frames. Deep enough to ride out a slow
# consumer moment, shallow enough that dropped-oldest keeps audio realtime.
_QUEUE_MAX_FRAMES = 40


@dataclass(slots=True)
class AlsaAudioIn:
    """Reads mono PCM16 from `arecord`."""

    config: AlsaAudioInConfig = field(default_factory=AlsaAudioInConfig)
    _process_factory: _ArecordProcessFactory | None = field(default=None)
    _process: _ArecordProcess | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    def __init__(
        self,
        config: AlsaAudioInConfig | None = None,
        _process_factory: _ArecordProcessFactory | None = None,
        **kwargs: Any,
    ) -> None:
        # The voice composition resolves adapters as ``factory(**selection.config)``,
        # so a YAML `config:` block arrives as flat keyword args — build the
        # config model from them. An explicit `config=` (tests) still wins.
        if config is None and kwargs:
            config = AlsaAudioInConfig(**kwargs)
        self.config = config or AlsaAudioInConfig()
        self._process_factory = _process_factory
        self._process = None
        self._closed = False

    @property
    def format(self) -> AudioFormat:
        return AudioFormat(
            sample_rate_hz=self.config.sample_rate_hz,
            channels=self.config.channels,
            sample_width_bytes=self.config.sample_width_bytes,
        )

    def stream(self) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            fmt = self.format
            frame_bytes = fmt.bytes_per_second * self.config.frame_ms // 1000
            proc = await self._ensure_process()
            stdout = proc.stdout
            if stdout is None:
                msg = "arecord subprocess has no stdout — cannot stream"
                raise RuntimeError(msg)

            # Continuous capture: a dedicated reader task drains arecord into a
            # bounded queue so the pipe NEVER backs up — even if the consumer
            # stalls (e.g. a slow downstream await), capture keeps running and
            # we drop the OLDEST frames instead of blocking arecord into an
            # ALSA overrun (which is what made the mic "cut out").
            queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=_QUEUE_MAX_FRAMES)

            async def _reader() -> None:
                try:
                    while not self._closed:
                        data = await stdout.readexactly(frame_bytes)
                        if queue.full():
                            with contextlib.suppress(asyncio.QueueEmpty):
                                queue.get_nowait()  # drop oldest, keep realtime
                        await queue.put(data)
                except (asyncio.IncompleteReadError, ConnectionResetError):
                    pass
                finally:
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(None)

            reader = asyncio.create_task(_reader(), name="alsa-capture")
            try:
                while not self._closed:
                    data = await queue.get()
                    if data is None:
                        break
                    yield AudioFrame(
                        pcm=data,
                        format=fmt,
                        monotonic_ns=time.monotonic_ns(),
                    )
            finally:
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reader

        return _gen()

    async def close(self) -> None:
        self._closed = True
        proc = self._process
        if proc is None:
            return
        self._process = None
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    async def _ensure_process(self) -> _ArecordProcess:
        proc = self._process
        if proc is not None and proc.returncode is None:
            return proc
        # arecord died (USB hiccup, ALSA error) — respawn instead of handing
        # back a corpse and going permanently deaf.
        self._process = None
        factory = self._process_factory or _DefaultArecordFactory()
        proc = await factory.spawn(self.config)
        self._process = proc
        return proc


# Built-in Jetson/G1 sound cards that are never the operator's microphone.
_BUILTIN_CARD_IDS = frozenset({"APE", "HDA", "NVIDIA"})

# `/proc/asound/cards` format:  " 0 [SF777W         ]: USB-Audio - SF-777W"
_PROC_CARD_RE = re.compile(r"^\s*\d+\s+\[(\w+)")
# `arecord -l` format:          "card 0: SF777W [SF-777W], device 0: ..."
_ARECORD_CARD_RE = re.compile(r"^card\s+\d+:\s+(\w+)\s")


def resolve_auto_device(cards_text: str) -> str:
    """Pick the first external (USB) capture card by NAME so the device
    string keeps working across re-enumeration. Accepts both
    ``/proc/asound/cards`` and ``arecord -l`` output."""
    for line in cards_text.splitlines():
        match = _PROC_CARD_RE.match(line) or _ARECORD_CARD_RE.match(line)
        if match and match.group(1) not in _BUILTIN_CARD_IDS:
            return f"plughw:CARD={match.group(1)}"
    return "default"


async def _resolve_device(device: str, arecord_path: str) -> str:
    # ``device: auto`` re-resolves to the current USB mic at every (re)spawn,
    # so swapping the microphone just works: the dead arecord respawns onto
    # whatever card is plugged in now.
    if device != "auto":
        return device
    try:
        cards_text = Path("/proc/asound/cards").read_text(encoding="utf-8")
    except OSError:
        # In a container only /dev/snd is mapped, /proc/asound is absent —
        # `arecord -l` enumerates capture cards via /dev/snd ioctls instead.
        try:
            proc = await asyncio.create_subprocess_exec(
                arecord_path,
                "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            cards_text = stdout.decode(errors="replace")
        except (OSError, TimeoutError):
            return "default"
    return resolve_auto_device(cards_text)


class _ArecordProcessFactory:
    """Spawn an arecord subprocess. Subclassed in tests."""

    async def spawn(self, config: AlsaAudioInConfig) -> _ArecordProcess:
        raise NotImplementedError


class _DefaultArecordFactory(_ArecordProcessFactory):
    async def spawn(self, config: AlsaAudioInConfig) -> _ArecordProcess:
        if shutil.which(config.arecord_path) is None:
            raise AlsaRuntimeNotAvailableError
        argv = [
            config.arecord_path,
            "-D",
            await _resolve_device(config.device, config.arecord_path),
            "-f",
            _format_flag(config),
            "-c",
            str(config.channels),
            "-r",
            str(config.sample_rate_hz),
            "-t",
            "raw",
            "--quiet",
        ]
        return await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )


def _format_flag(config: AlsaAudioInConfig) -> str:
    try:
        return _ARECORD_FORMAT_FLAGS[config.sample_width_bytes]
    except KeyError as exc:
        msg = f"unsupported sample width: {config.sample_width_bytes}"
        raise ValueError(msg) from exc


_ARECORD_FORMAT_FLAGS: dict[int, str] = {
    2: "S16_LE",
    4: "S32_LE",
}
