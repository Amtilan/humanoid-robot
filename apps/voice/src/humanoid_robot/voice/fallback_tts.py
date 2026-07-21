"""TTS with an offline fallback: cloud voice first, local Piper when it fails.

Mirrors the ``SwitchableAsr`` philosophy — the cloud gives quality (a real
Kazakh voice), the local model guarantees the robot never goes mute when the
internet does (plan acceptance §8.5).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from humanoid_robot.observability import get_logger
from humanoid_robot.ports import AudioFrame, TtsPort, TtsRequest

_LOG = get_logger("cortex-voice.fallback_tts")


class FallbackTts:
    """TtsPort chaining a primary and a fallback implementation."""

    def __init__(self, primary: TtsPort, fallback: TtsPort) -> None:
        self._primary = primary
        self._fallback = fallback

    async def synthesize(self, request: TtsRequest) -> AudioFrame:
        try:
            return await self._primary.synthesize(request)
        except Exception:
            _LOG.warning("tts.primary_failed_falling_back", exc_info=True)
            return await self._fallback.synthesize(request)

    async def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]:
        emitted = False
        try:
            async for frame in self._primary.synthesize_stream(request):
                emitted = True
                yield frame
        except Exception:
            _LOG.warning("tts.primary_stream_failed", emitted=emitted, exc_info=True)
            if emitted:
                # Mid-utterance failure: stop cleanly rather than restarting
                # the sentence in a different voice.
                return
        else:
            return
        async for frame in self._fallback.synthesize_stream(request):
            yield frame
