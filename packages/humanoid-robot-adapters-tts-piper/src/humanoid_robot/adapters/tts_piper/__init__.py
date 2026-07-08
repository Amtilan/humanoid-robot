"""TTS adapter: Piper (ONNX)."""

from humanoid_robot.adapters.tts_piper.adapter import (
    PiperConfig,
    PiperRuntimeNotAvailableError,
    PiperTts,
    PiperVoiceNotConfiguredError,
)

__all__ = [
    "PiperConfig",
    "PiperRuntimeNotAvailableError",
    "PiperTts",
    "PiperVoiceNotConfiguredError",
]
