"""DDS state subscribers — feed the IMU / temperature / battery ports.

The G1 publishes two low-rate state topics we care about:
  * ``rt/lowstate`` (``unitree_hg LowState_``) — IMU (quaternion / gyro /
    accel / rpy / board temp) and per-motor state (winding temperatures).
  * ``rt/lf/bmsstate`` (``unitree_hg BmsState_``) — battery ``soc`` (0-100),
    soh, voltage, current.  ``LowState_`` itself carries no BMS field, so
    the SOC lives on this separate topic (confirmed live on the robot:
    ``rt/lf/bmsstate`` → soc=87).

Bridging note: the SDK delivers frames on its own DDS thread, while the
telemetry pump reads on the asyncio loop.  Rather than hop threads with
``run_coroutine_threadsafe`` we expose plain *sync* getters and wire them
into the ports' ``source`` hook — ``UnitreeG1Imu.read()`` /
``UnitreeG1Temperature.read()`` / ``UnitreeG1Battery.read_percentage()``
already call ``source()`` synchronously, so the only shared state is a
lock-guarded snapshot and there's no async hand-off.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from humanoid_robot.observability import get_logger

_LOG = get_logger("cortex-adapters.g1.lowstate")

LOWSTATE_TOPIC = "rt/lowstate"
BMS_TOPIC = "rt/lf/bmsstate"

# Minimum array lengths before we trust a vendor IMU field.
_VEC3 = 3  # rpy / gyroscope / accelerometer
_QUAT = 4  # quaternion (w, x, y, z)
_SOC_FULL = 100.0  # BmsState_.soc is a 0-100 percentage


def _seq(value: Any) -> list[float]:  # noqa: ANN401 -- vendor arrays are untyped
    """Coerce a CycloneDDS array (or any iterable) to a list of floats."""
    if value is None:
        return []
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        return []


def decode_imu(msg: Any) -> dict[str, float]:  # noqa: ANN401 -- vendor msg is untyped
    """LowState_ -> imu sample dict (empty keys omitted)."""
    imu = getattr(msg, "imu_state", None)
    if imu is None:
        return {}
    out: dict[str, float] = {}
    rpy = _seq(getattr(imu, "rpy", None))
    if len(rpy) >= _VEC3:
        out["roll_rad"], out["pitch_rad"], out["yaw_rad"] = rpy[0], rpy[1], rpy[2]
    gyro = _seq(getattr(imu, "gyroscope", None))
    if len(gyro) >= _VEC3:
        out["gyro_x"], out["gyro_y"], out["gyro_z"] = gyro[0], gyro[1], gyro[2]
    acc = _seq(getattr(imu, "accelerometer", None))
    if len(acc) >= _VEC3:
        out["accel_x"], out["accel_y"], out["accel_z"] = acc[0], acc[1], acc[2]
    quat = _seq(getattr(imu, "quaternion", None))
    if len(quat) >= _QUAT:
        out["quat_w"], out["quat_x"], out["quat_y"], out["quat_z"] = (
            quat[0],
            quat[1],
            quat[2],
            quat[3],
        )
    return out


def decode_temperature(msg: Any) -> dict[str, float]:  # noqa: ANN401
    """LowState_ -> temperature sample dict (board + motor summary)."""
    out: dict[str, float] = {}
    imu = getattr(msg, "imu_state", None)
    if imu is not None:
        board = getattr(imu, "temperature", None)
        if board is not None:
            with contextlib.suppress(TypeError, ValueError):
                out["imu"] = float(board)
    motors = getattr(msg, "motor_state", None) or []
    temps: list[float] = []
    for m in motors:
        mt = _seq(getattr(m, "temperature", None))
        if mt:
            temps.append(mt[0])  # [0] = winding/main temp
    if temps:
        out["motor_max"] = max(temps)
        out["motor_mean"] = sum(temps) / len(temps)
    return out


def decode_battery(msg: Any) -> float | None:  # noqa: ANN401
    """BmsState_ -> battery fraction in [0, 1], or None if unreadable."""
    soc = getattr(msg, "soc", None)
    if soc is None:
        return None
    try:
        frac = float(soc) / _SOC_FULL
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, frac))


def _load_lowstate_types() -> tuple[Any, Any, Any]:
    """Deferred SDK import — kept out of module import so this file loads
    off-robot (CI, dev laptops) where the vendor SDK is absent."""
    from unitree_sdk2py.core.channel import (  # type: ignore[import-not-found]
        ChannelSubscriber,
    )
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import (  # type: ignore[import-not-found]
        BmsState_,
        LowState_,
    )

    return ChannelSubscriber, LowState_, BmsState_


class G1LowStateReader:
    """Subscribes to ``rt/lowstate`` and caches the latest decoded frame.

    ``ChannelFactoryInitialize`` must have run first (the adapter does it
    in ``start()``). Call ``start()`` to open the subscription; then wire
    ``imu_sample`` / ``temperature_sample`` into the ports' ``source``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._imu: dict[str, float] = {}
        self._temp: dict[str, float] = {}
        self._battery: float = 0.0
        self._low_sub: Any = None
        self._bms_sub: Any = None
        self._seen = False

    def start(self, *, queue_len: int = 10) -> None:
        channel_subscriber, low_state, bms_state = _load_lowstate_types()
        self._low_sub = channel_subscriber(LOWSTATE_TOPIC, low_state)
        self._low_sub.Init(self._on_lowstate, queue_len)
        # Battery is a separate topic; a BMS failure must not sink the IMU
        # + temperature stream, so it's independently guarded.
        try:
            self._bms_sub = channel_subscriber(BMS_TOPIC, bms_state)
            self._bms_sub.Init(self._on_bms, queue_len)
        except Exception:
            _LOG.exception("g1.bmsstate.subscribe_failed")

    def _on_lowstate(self, msg: Any) -> None:  # noqa: ANN401 -- DDS callback, untyped msg
        try:
            imu = decode_imu(msg)
            temp = decode_temperature(msg)
        except Exception:  # never let a bad frame kill the DDS thread
            _LOG.exception("g1.lowstate.decode_failed")
            return
        with self._lock:
            self._imu = imu
            self._temp = temp
            if not self._seen:
                self._seen = True
                _LOG.info(
                    "g1.lowstate.first_frame",
                    imu_keys=sorted(imu),
                    temp_keys=sorted(temp),
                )

    def _on_bms(self, msg: Any) -> None:  # noqa: ANN401 -- DDS callback, untyped msg
        try:
            frac = decode_battery(msg)
        except Exception:
            _LOG.exception("g1.bmsstate.decode_failed")
            return
        if frac is None:
            return
        with self._lock:
            self._battery = frac

    # -- sync getters wired into the port `source` hooks -----------------
    def imu_sample(self) -> dict[str, float]:
        with self._lock:
            return dict(self._imu)

    def temperature_sample(self) -> dict[str, float]:
        with self._lock:
            return dict(self._temp)

    def battery_percentage(self) -> float:
        with self._lock:
            return self._battery
