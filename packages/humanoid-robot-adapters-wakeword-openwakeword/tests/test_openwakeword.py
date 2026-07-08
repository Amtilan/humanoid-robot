"""OpenWakeWord tests with an injected fake detector."""

from __future__ import annotations

import pytest

from humanoid_robot.adapters.wakeword_openwakeword import (
    OpenWakeWord,
    OpenWakeWordConfig,
    OpenWakeWordRuntimeNotAvailableError,
)
from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


def _frame(samples: int) -> AudioFrame:
    return AudioFrame(pcm=b"\x00\x01" * samples, format=_FMT, monotonic_ns=0)


class TestOpenWakeWord:
    async def test_missing_runtime_raises(self) -> None:
        detector = OpenWakeWord(OpenWakeWordConfig(model_paths=("/x.onnx",)))
        with pytest.raises(OpenWakeWordRuntimeNotAvailableError):
            await detector.feed(_frame(1_280))

    async def test_partial_frame_returns_none(self) -> None:
        calls: list[int] = []

        def det(samples: list[int]) -> dict[str, float]:
            calls.append(len(samples))
            return {"hey_robot": 0.99}

        detector = OpenWakeWord(OpenWakeWordConfig(), detector=det)
        result = await detector.feed(_frame(600))  # < 1280
        assert result is None
        assert calls == []

    async def test_score_below_threshold_returns_none(self) -> None:
        detector = OpenWakeWord(
            OpenWakeWordConfig(threshold=0.7),
            detector=lambda _: {"hey_robot": 0.4},
        )
        result = await detector.feed(_frame(1_280))
        assert result is None

    async def test_score_above_threshold_returns_event(self) -> None:
        detector = OpenWakeWord(
            OpenWakeWordConfig(threshold=0.5),
            detector=lambda _: {"hey_robot": 0.9},
        )
        result = await detector.feed(_frame(1_280))
        assert result is not None
        assert result.word == "hey_robot"
        assert result.score == pytest.approx(0.9)

    async def test_highest_scoring_word_wins(self) -> None:
        detector = OpenWakeWord(
            OpenWakeWordConfig(threshold=0.5),
            detector=lambda _: {"a": 0.6, "b": 0.95, "c": 0.7},
        )
        result = await detector.feed(_frame(1_280))
        assert result is not None
        assert result.word == "b"

    def test_keywords_derived_from_model_paths(self) -> None:
        detector = OpenWakeWord(
            OpenWakeWordConfig(model_paths=("/opt/wake/hey_robot.onnx", "/opt/wake/robot.onnx"))
        )
        assert set(detector.keywords()) == {"hey_robot", "robot"}

    async def test_rejects_wrong_sample_rate(self) -> None:
        detector = OpenWakeWord(
            OpenWakeWordConfig(),
            detector=lambda _: {"hey_robot": 0.9},
        )
        wrong = AudioFormat(sample_rate_hz=48_000, channels=1, sample_width_bytes=2)
        with pytest.raises(ValueError, match="16000"):
            await detector.feed(AudioFrame(pcm=b"\x00" * 2560, format=wrong, monotonic_ns=0))
