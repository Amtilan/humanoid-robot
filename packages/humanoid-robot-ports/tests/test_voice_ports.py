"""Voice port protocol shape tests."""

from __future__ import annotations

import humanoid_robot.ports as ports
from humanoid_robot.ports.voice import VadDecision, WakeWordEvent


class TestVoicePorts:
    def test_vad_port_is_protocol(self) -> None:
        assert getattr(ports.VadPort, "_is_protocol", False)

    def test_wake_word_port_is_protocol(self) -> None:
        assert getattr(ports.WakeWordPort, "_is_protocol", False)

    def test_vad_decision_is_frozen_bounded_probability(self) -> None:
        d = VadDecision(is_speech=True, speech_probability=0.75)
        assert d.speech_probability == 0.75

    def test_wake_word_event_shape(self) -> None:
        ev = WakeWordEvent(word="hey_robot", score=0.98)
        assert ev.word == "hey_robot"
