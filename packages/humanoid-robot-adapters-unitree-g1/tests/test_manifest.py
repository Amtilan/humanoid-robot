"""Manifest builder tests — no SDK required."""

from __future__ import annotations

from humanoid_robot.adapters.unitree_g1 import build_manifest
from humanoid_robot.adapters.unitree_g1.manifest import G1_GESTURES
from humanoid_robot.domain.robot import LocomotionKind


class TestBuildManifest:
    def test_defaults_declare_bipedal_locomotion(self) -> None:
        m = build_manifest(network_interface="eth10")
        assert m.capabilities.locomotion is not None
        assert m.capabilities.locomotion.kind == LocomotionKind.LEGGED_BIPEDAL
        assert m.capabilities.locomotion.max_speed_mps == 1.5

    def test_two_arms_with_full_gesture_set(self) -> None:
        m = build_manifest(network_interface="eth10")
        assert len(m.capabilities.arms) == 2
        for arm in m.capabilities.arms:
            assert arm.gestures == G1_GESTURES

    def test_g1_mic_kind_when_source_is_g1(self) -> None:
        m = build_manifest(network_interface="eth10", mic_source="g1")
        assert m.capabilities.audio_in is not None
        assert m.capabilities.audio_in.kind == "g1_multicast"

    def test_alsa_mic_kind_when_source_is_alsa(self) -> None:
        m = build_manifest(network_interface="eth10", mic_source="alsa")
        assert m.capabilities.audio_in is not None
        assert m.capabilities.audio_in.kind == "alsa"

    def test_hand_kind_none_means_zero_dof(self) -> None:
        m = build_manifest(network_interface="eth10", hand_kind="none")
        for hand in m.capabilities.hands:
            assert hand.dof == 0

    def test_hand_kind_dex3_means_six_dof(self) -> None:
        m = build_manifest(network_interface="eth10", hand_kind="dex3")
        for hand in m.capabilities.hands:
            assert hand.dof == 6

    def test_network_interface_recorded(self) -> None:
        m = build_manifest(network_interface="eth10")
        assert m.network_interface == "eth10"
        assert m.transport_hint == "cyclonedds"
