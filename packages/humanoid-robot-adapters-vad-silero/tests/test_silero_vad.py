"""SileroVad tests with an injected predictor — no ONNX or torch needed."""

from __future__ import annotations

import pytest

from humanoid_robot.adapters.vad_silero import (
    SileroConfig,
    SileroRuntimeNotAvailableError,
    SileroVad,
)
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_G1_FORMAT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


def _frame(samples: int) -> AudioFrame:
    return AudioFrame(pcm=b"\x00\x00" * samples, format=_G1_FORMAT, monotonic_ns=0)


class TestSileroVad:
    async def test_missing_runtime_raises(self) -> None:
        vad = SileroVad()
        with pytest.raises(SileroRuntimeNotAvailableError):
            await vad.decide(_frame(512))

    async def test_partial_frame_does_not_call_predictor(self) -> None:
        calls: list[list[float]] = []

        def predictor(s: list[float]) -> float:
            calls.append(s)
            return 0.9

        vad = SileroVad(predictor=predictor)
        # 300 samples < 512 → no predictor call yet.
        result = await vad.decide(_frame(300))
        assert calls == []
        assert result.speech_probability == 0.0

    async def test_full_frame_triggers_predictor(self) -> None:
        vad = SileroVad(predictor=lambda _: 0.9)
        result = await vad.decide(_frame(512))
        assert result.speech_probability == pytest.approx(0.9)
        assert result.is_speech

    async def test_speech_probability_below_threshold_is_not_speech(self) -> None:
        vad = SileroVad(
            config=SileroConfig(threshold=0.7),
            predictor=lambda _: 0.4,
        )
        result = await vad.decide(_frame(512))
        assert not result.is_speech

    async def test_reset_clears_state(self) -> None:
        vad = SileroVad(predictor=lambda _: 0.9)
        await vad.decide(_frame(512))
        await vad.reset()
        # Buffer cleared, probability reset.
        r = await vad.decide(_frame(300))
        assert r.speech_probability == 0.0

    async def test_rejects_wrong_sample_rate(self) -> None:
        vad = SileroVad(predictor=lambda _: 0.9)
        wrong = AudioFormat(sample_rate_hz=48_000, channels=1, sample_width_bytes=2)
        f = AudioFrame(pcm=b"\x00\x00" * 512, format=wrong, monotonic_ns=0)
        with pytest.raises(ValueError, match="16000"):
            await vad.decide(f)
