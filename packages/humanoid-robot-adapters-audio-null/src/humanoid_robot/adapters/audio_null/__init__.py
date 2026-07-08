"""Null audio adapters — silence in, discard out."""

from humanoid_robot.adapters.audio_null.adapter import (
    NullAudioIn,
    NullAudioInConfig,
    NullAudioOut,
    build_null_audio_in,
    build_null_audio_out,
)

__all__ = [
    "NullAudioIn",
    "NullAudioInConfig",
    "NullAudioOut",
    "build_null_audio_in",
    "build_null_audio_out",
]
