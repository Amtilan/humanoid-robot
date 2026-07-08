"""System diagnostics — host metrics + optional Jetson GPU stats.

Kept out of the observability package on purpose: this module is a
snapshot-style provider tailored to the operator dashboard, not a
sampling exporter.  For long-term series use the Prometheus scrape
endpoint (see cortex-core `/metrics`).
"""

from __future__ import annotations

import importlib
import shutil
from typing import Any, cast

from pydantic import BaseModel, ConfigDict


class CpuStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    percent: float
    per_core_percent: list[float]
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    core_count: int


class MemoryStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float
    swap_total_bytes: int
    swap_used_bytes: int


class DiskStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class HostDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    uptime_s: float
    cpu: CpuStats
    memory: MemoryStats
    disks: list[DiskStats]


class GpuStats(BaseModel):
    """Best-effort Jetson metrics via `jtop`. Empty when jtop is not installed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: bool
    gpu_percent: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    temperature_c: float | None = None
    power_w: float | None = None
    detail: str | None = None


def collect_host() -> HostDiagnostics:
    psutil = _psutil()
    per_core = [float(x) for x in psutil.cpu_percent(interval=None, percpu=True)]
    total = float(psutil.cpu_percent(interval=None, percpu=False))
    try:
        load1, load5, load15 = psutil.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = 0.0
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disks: list[DiskStats] = []
    for mount in ("/", "/var"):
        try:
            usage = psutil.disk_usage(mount)
        except FileNotFoundError:
            continue
        disks.append(
            DiskStats(
                path=mount,
                total_bytes=int(usage.total),
                used_bytes=int(usage.used),
                free_bytes=int(usage.free),
                percent=float(usage.percent),
            )
        )
    uptime_s = max(0.0, float(psutil.boot_time()))
    now = psutil.time.time() if hasattr(psutil, "time") else 0.0
    if now:
        uptime_s = max(0.0, now - uptime_s)
    return HostDiagnostics(
        uptime_s=uptime_s,
        cpu=CpuStats(
            percent=total,
            per_core_percent=per_core,
            load_avg_1m=float(load1),
            load_avg_5m=float(load5),
            load_avg_15m=float(load15),
            core_count=int(psutil.cpu_count(logical=True) or len(per_core) or 0),
        ),
        memory=MemoryStats(
            total_bytes=int(mem.total),
            used_bytes=int(mem.used),
            available_bytes=int(mem.available),
            percent=float(mem.percent),
            swap_total_bytes=int(swap.total),
            swap_used_bytes=int(swap.used),
        ),
        disks=disks,
    )


def collect_gpu() -> GpuStats:
    """Best-effort snapshot from `jtop` (Jetson-only), else supported=False."""
    if shutil.which("tegrastats") is None and not _try_import("jtop"):
        return GpuStats(supported=False, detail="jtop / tegrastats not available")

    try:
        jtop_module = importlib.import_module("jtop")
    except ImportError as exc:
        return GpuStats(supported=False, detail=f"jtop import failed: {exc}")

    jtop_cls = getattr(jtop_module, "jtop", None)
    if jtop_cls is None:
        return GpuStats(supported=False, detail="jtop.jtop unavailable")

    try:
        with jtop_cls() as sess:
            if not sess.ok():
                return GpuStats(supported=False, detail="jtop session not ok")
            snapshot = _extract_jtop_snapshot(sess)
    except Exception as exc:
        return GpuStats(supported=False, detail=f"jtop error: {exc}")

    return snapshot


def _extract_jtop_snapshot(sess: Any) -> GpuStats:  # noqa: ANN401 -- untyped jtop.jtop
    gpu_percent = None
    ram_used = ram_total = None
    temperature = None
    power = None
    gpu = getattr(sess, "gpu", None)
    if isinstance(gpu, dict):
        raw_gpu_percent = _first(gpu.values(), key="load")
        if raw_gpu_percent is not None:
            gpu_percent = float(raw_gpu_percent)
    ram = getattr(sess, "ram", None)
    if isinstance(ram, dict):
        ram_used = _as_int(ram.get("used"))
        ram_total = _as_int(ram.get("tot"))
    temp = getattr(sess, "temperature", None)
    if isinstance(temp, dict):
        temperature = _first(temp.values(), key="temp")
    power = _as_float(getattr(sess, "power", None), key="tot")
    return GpuStats(
        supported=True,
        gpu_percent=gpu_percent,
        ram_used_bytes=ram_used * 1024 if ram_used is not None else None,
        ram_total_bytes=ram_total * 1024 if ram_total is not None else None,
        temperature_c=temperature,
        power_w=power,
    )


def _first(values: Any, *, key: str) -> float | None:  # noqa: ANN401 -- jtop payloads
    for entry in values:
        if isinstance(entry, dict) and key in entry:
            return _as_float(entry, key=key)
        if isinstance(entry, (int, float)):
            return float(entry)
    return None


def _as_int(value: Any) -> int | None:  # noqa: ANN401 -- jtop payloads
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _as_float(value: Any, *, key: str | None = None) -> float | None:  # noqa: ANN401
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and key is not None:
        v = value.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _try_import(module: str) -> bool:
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


def _psutil() -> Any:  # noqa: ANN401 -- psutil ships no type stubs
    return cast(Any, importlib.import_module("psutil"))
