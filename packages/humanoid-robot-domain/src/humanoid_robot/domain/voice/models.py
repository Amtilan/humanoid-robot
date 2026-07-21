"""Voice domain — value objects for audio, transcriptions, utterances."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from humanoid_robot.domain.shared import SessionId, Timestamp, UtteranceId, utc_now


class Language(StrEnum):
    """BCP-47 tags, restricted to the subset the platform officially supports.

    Adding a new language is a governance decision — extend this enum and add
    an ASR/TTS voice for it before shipping.
    """

    RU = "ru"
    EN = "en"
    KK = "kk"
    UNKNOWN = "und"


class AudioFormat(BaseModel):
    """Description of a raw PCM audio stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_rate_hz: int = Field(gt=0, le=192_000)
    channels: int = Field(ge=1, le=8)
    sample_width_bytes: int = Field(ge=1, le=4)

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate_hz * self.channels * self.sample_width_bytes


class UtteranceRole(StrEnum):
    """Who produced the utterance."""

    USER = "user"
    ROBOT = "robot"
    SYSTEM = "system"


class TranscriptionSegment(BaseModel):
    """A single time-aligned segment inside a transcription."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_bounds(self) -> Self:
        if self.end_ms < self.start_ms:
            msg = "end_ms must be >= start_ms"
            raise ValueError(msg)
        return self


class Transcription(BaseModel):
    """Final ASR output for one utterance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    language: Language
    confidence: float = Field(ge=0.0, le=1.0)
    segments: tuple[TranscriptionSegment, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class Utterance(BaseModel):
    """A single speech act within a session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UtteranceId
    session_id: SessionId
    role: UtteranceRole
    text: str
    language: Language
    created_at: Timestamp = Field(default_factory=utc_now)
