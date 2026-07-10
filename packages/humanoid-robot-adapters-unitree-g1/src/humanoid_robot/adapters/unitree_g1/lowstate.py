"""DDS ``rt/lowstate`` subscriber — feeds the IMU + temperature ports.

The G1 publishes ``unitree_hg`` ``LowState_`` on ``rt/lowstate`` at ~500 Hz:
IMU (quaternion / gyro / accel / rpy / board temp) and per-motor state
(including winding temperatures).  We subscribe once, decode each frame
into plain dicts, and cache the latest under a lock.

Bridging note: the SDK delivers frames on its own DDS thread, while the
telemetry pump reads on the asyncio loop.  Rather than hop threads with
``run_coroutine_threadsafe`` we expose plain *sync* getters and wire them
into the ports' ``source`` hook — ``UnitreeG1Imu.read()`` /
``UnitreeG1Temperature.read()`` already call ``source()`` synchronously,
so the only shared state is the guarded ``dict`` and there's no async
hand-off.

Battery SOC is deliberately absent: ``unitree_hg`` ``LowState_`` carries
no BMS field, so the battery port stays sourceless (reports 0.0) until a
dedicated BMS topic is wired.
"""

from __future__ import annotations

import threading
from typing import Any

from humanoid_robot.observability import get_logger

_LOG = get_logger("cortex-adapters.g1.lowstate")

LOWSTATE_TOPIC = "rt/lowstate"


def _seq(value: object) -> list[float]:
    """Coerce a CycloneDDS array (or any iterable) to a list of floats."""
    if value is None:
        return []
    try:
        return [float(x) for x in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return []


def decode_imu(msg: Any) -> dict[str, float]:  # noqa: ANN401 -- vendor msg is untyped
    """LowState_ -> imu sample dict (empty keys omitted)."""
    imu = getattr(msg, "imu_state", None)
    if imu is None:
        return {}
    out: dict[str, float] = {}
    rpy = _seq(getattr(imu, "rpy", None))
    if len(rpy) >= 3:
        out["roll_rad"], out["pitch_rad"], out["yaw_rad"] = rpy[0], rpy[1], rpy[2]
    gyro = _seq(getattr(imu, "gyroscope", None))
    if len(gyro) >= 3:
        out["gyro_x"], out["gyro_y"], out["gyro_z"] = gyro[0], gyro[1], gyro[2]
    acc = _seq(getattr(imu, "accelerometer", None))
    if len(acc) >= 3:
        out["accel_x"], out["accel_y"], out["accel_z"] = acc[0], acc[1], acc[2]
    quat = _seq(getattr(imu, "quaternion", None))
    if len(quat) >= 4:
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
            try:
                out["imu"] = float(board)
            except (TypeError, ValueError):
                pass
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


def _load_lowstate_types() -> tuple[Any, Any]:
    """Deferred SDK import — kept out of module import so this file loads
    off-robot (CI, dev laptops) where the vendor SDK is absent."""
    from unitree_sdk2py.core.channel import ChannelSubscriber
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

    return ChannelSubscriber, LowState_


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
        self._sub: Any = None
        self._seen = False

    def start(self, *, queue_len: int = 10) -> None:
        channel_subscriber, low_state = _load_lowstate_types()
        self._sub = channel_subscriber(LOWSTATE_TOPIC, low_state)
        self._sub.Init(self._on_message, queue_len)

    def _on_message(self, msg: Any) -> None:  # noqa: ANN401 -- DDS callback, untyped msg
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

    # -- sync getters wired into the port `source` hooks -----------------
    def imu_sample(self) -> dict[str, float]:
        with self._lock:
            return dict(self._imu)

    def temperature_sample(self) -> dict[str, float]:
        with self._lock:
            return dict(self._temp)
