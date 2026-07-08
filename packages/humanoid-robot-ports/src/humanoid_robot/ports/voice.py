"""Voice-pipeline ports — VAD, wake-word, and future noise suppression."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.ports.robot import AudioFrame


class VadDecision(BaseModel):
    """One frame-level decision from a voice activity detector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_speech: bool
    speech_probability: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class VadPort(Protocol):
    """Frame-level voice activity detection.

    Callers push `AudioFrame`s and receive a per-frame `VadDecision`. The
    detector keeps its own state — implementations may internally buffer to
    the frame size their model expects.
    """

    async def decide(self, frame: AudioFrame) -> VadDecision: ...

    async def reset(self) -> None: ...


class WakeWordEvent(BaseModel):
    """Structured wake-word detection event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    word: str
    score: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class WakeWordPort(Protocol):
    """Wake-word detection (e.g. openWakeWord).

    The detector keeps its own window; `feed(frame)` returns `None` when no
    trigger has fired and a `WakeWordEvent` on detection.
    """

    async def feed(self, frame: AudioFrame) -> WakeWordEvent | None: ...

    def keywords(self) -> tuple[str, ...]: ...
