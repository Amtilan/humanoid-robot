"""ASR adapter: faster-whisper (CT2 INT8)."""

from humanoid_robot.adapters.asr_whisper.adapter import (
    FasterWhisperAsr,
    FasterWhisperConfig,
    WhisperRuntimeNotAvailableError,
)

__all__ = [
    "FasterWhisperAsr",
    "FasterWhisperConfig",
    "WhisperRuntimeNotAvailableError",
]
