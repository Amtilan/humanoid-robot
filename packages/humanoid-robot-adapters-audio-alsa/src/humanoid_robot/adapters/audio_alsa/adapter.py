"""AudioInPort backed by an ``arecord`` subprocess.

The subprocess emits raw PCM on stdout at a fixed rate/width/channels;
`AlsaAudioIn` reads it in frame-sized chunks and yields `AudioFrame`s.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

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


@dataclass(slots=True)
class AlsaAudioIn:
    """Reads mono PCM16 from `arecord`."""

    config: AlsaAudioInConfig = field(default_factory=AlsaAudioInConfig)
    _process_factory: _ArecordProcessFactory | None = field(default=None)
    _process: _ArecordProcess | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

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
            while not self._closed:
                data = await stdout.readexactly(frame_bytes)
                yield AudioFrame(
                    pcm=data,
                    format=fmt,
                    monotonic_ns=time.monotonic_ns(),
                )

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
        if self._process is not None:
            return self._process
        factory = self._process_factory or _DefaultArecordFactory()
        proc = await factory.spawn(self.config)
        self._process = proc
        return proc


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
            config.device,
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
