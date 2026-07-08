"""Voice domain tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from humanoid_robot.domain.voice import (
    AudioFormat,
    Language,
    Transcription,
    TranscriptionSegment,
    Utterance,
    UtteranceRole,
)


class TestAudioFormat:
    def test_bytes_per_second_computes(self) -> None:
        fmt = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)
        assert fmt.bytes_per_second == 32_000

    @pytest.mark.parametrize(
        ("sr", "ch", "sw"),
        [
            (0, 1, 2),  # sample rate must be > 0
            (16_000, 0, 2),  # channels >= 1
            (16_000, 1, 5),  # sample width <= 4
        ],
    )
    def test_rejects_out_of_range(self, sr: int, ch: int, sw: int) -> None:
        with pytest.raises(ValidationError):
            AudioFormat(sample_rate_hz=sr, channels=ch, sample_width_bytes=sw)

    def test_is_frozen(self) -> None:
        fmt = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)
        with pytest.raises(ValidationError):
            fmt.sample_rate_hz = 48_000  # type: ignore[misc]  # frozen model


class TestTranscriptionSegment:
    def test_rejects_negative_time(self) -> None:
        with pytest.raises(ValidationError):
            TranscriptionSegment(text="hi", start_ms=-1, end_ms=100, confidence=0.9)

    def test_rejects_reversed_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TranscriptionSegment(text="hi", start_ms=200, end_ms=100, confidence=0.9)

    def test_accepts_zero_length(self) -> None:
        seg = TranscriptionSegment(text="", start_ms=100, end_ms=100, confidence=0.0)
        assert seg.start_ms == seg.end_ms


class TestTranscription:
    def test_is_empty_true_for_whitespace(self) -> None:
        tr = Transcription(text="   \n\t", language=Language.RU, confidence=0.5)
        assert tr.is_empty

    def test_is_empty_false_for_content(self) -> None:
        tr = Transcription(text="hello", language=Language.EN, confidence=1.0)
        assert not tr.is_empty


class TestUtterance:
    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            Utterance.model_validate(
                {
                    "id": "utt_1",
                    "session_id": "ses_1",
                    "role": UtteranceRole.USER,
                    "text": "hi",
                    "language": Language.EN,
                    "extra_field": "nope",
                }
            )
