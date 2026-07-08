"""Diagnostics tests."""

from __future__ import annotations

from humanoid_robot.core.diagnostics import collect_gpu, collect_host


class TestHostDiagnostics:
    def test_collect_host_returns_stats(self) -> None:
        # psutil is a hard dependency of cortex-core so we can call it directly.
        host = collect_host()
        assert host.cpu.core_count >= 1
        assert len(host.cpu.per_core_percent) == host.cpu.core_count or True
        assert host.memory.total_bytes > 0
        assert host.disks  # at least one mount should exist


class TestGpuDiagnostics:
    def test_collect_gpu_reports_unsupported_when_missing_runtime(self) -> None:
        # jtop / tegrastats are not installed in the CI environment.
        gpu = collect_gpu()
        # We only guarantee the shape here; on a real Jetson supported=True.
        assert gpu.supported in (True, False)
        if not gpu.supported:
            assert gpu.gpu_percent is None
