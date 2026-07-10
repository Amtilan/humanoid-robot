"""Tests for the rt/lowstate decoder + reader (no vendor SDK needed)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from humanoid_robot.adapters.unitree_g1.lowstate import (
    G1LowStateReader,
    decode_imu,
    decode_temperature,
)


def _imu(**kw: object) -> SimpleNamespace:
    return SimpleNamespace(
        rpy=kw.get("rpy", [0.1, 0.2, 0.3]),
        gyroscope=kw.get("gyroscope", [1.0, 2.0, 3.0]),
        accelerometer=kw.get("accelerometer", [0.0, 0.0, 9.8]),
        quaternion=kw.get("quaternion", [1.0, 0.0, 0.0, 0.0]),
        temperature=kw.get("temperature", 41),
    )


def _motor(t0: int, t1: int = 0) -> SimpleNamespace:
    return SimpleNamespace(temperature=[t0, t1])


def _lowstate(imu: object, motors: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(imu_state=imu, motor_state=motors)


class TestDecodeImu:
    def test_full_frame_maps_all_axes(self) -> None:
        out = decode_imu(_lowstate(_imu(), []))
        assert out["roll_rad"] == 0.1
        assert out["pitch_rad"] == 0.2
        assert out["yaw_rad"] == 0.3
        assert out["gyro_x"] == 1.0
        assert out["gyro_z"] == 3.0
        assert out["accel_z"] == 9.8
        assert out["quat_w"] == 1.0

    def test_missing_imu_state_is_empty(self) -> None:
        assert decode_imu(SimpleNamespace(imu_state=None, motor_state=[])) == {}

    def test_short_arrays_are_skipped_not_crashed(self) -> None:
        imu = SimpleNamespace(
            rpy=[0.1, 0.2],  # too short → skipped
            gyroscope=[1.0, 2.0, 3.0],
            accelerometer=[],
            quaternion=[1.0, 0.0],
            temperature=30,
        )
        out = decode_imu(_lowstate(imu, []))
        assert "roll_rad" not in out
        assert out["gyro_y"] == 2.0
        assert "accel_x" not in out
        assert "quat_w" not in out


class TestDecodeTemperature:
    def test_board_and_motor_summary(self) -> None:
        motors = [_motor(40), _motor(55), _motor(48)]
        out = decode_temperature(_lowstate(_imu(temperature=42), motors))
        assert out["imu"] == 42.0
        assert out["motor_max"] == 55.0
        assert out["motor_mean"] == (40 + 55 + 48) / 3

    def test_no_motors_only_board(self) -> None:
        out = decode_temperature(_lowstate(_imu(temperature=39), []))
        assert out["imu"] == 39.0
        assert "motor_max" not in out

    def test_empty_message(self) -> None:
        out = decode_temperature(SimpleNamespace(imu_state=None, motor_state=[]))
        assert out == {}


class TestReader:
    def test_getters_reflect_last_message(self) -> None:
        reader = G1LowStateReader()
        # feed a frame straight through the DDS callback (bypasses SDK)
        reader._on_message(_lowstate(_imu(), [_motor(50), _motor(60)]))
        imu = reader.imu_sample()
        temp = reader.temperature_sample()
        assert imu["yaw_rad"] == 0.3
        assert temp["motor_max"] == 60.0
        # getters return copies — mutating one doesn't corrupt the cache
        imu["yaw_rad"] = 999.0
        assert reader.imu_sample()["yaw_rad"] == 0.3

    def test_getters_empty_before_first_message(self) -> None:
        reader = G1LowStateReader()
        assert reader.imu_sample() == {}
        assert reader.temperature_sample() == {}

    def test_bad_frame_does_not_raise(self) -> None:
        reader = G1LowStateReader()
        reader._on_message(object())  # no imu_state/motor_state attrs
        # decode returns {} for a shapeless object; no exception escapes
        assert reader.imu_sample() == {}
