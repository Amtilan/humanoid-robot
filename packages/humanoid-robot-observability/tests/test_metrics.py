"""Tests for the Prometheus wrappers."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from humanoid_robot.observability import PromMetrics


class TestPromMetrics:
    def test_rejects_names_without_hr_prefix(self) -> None:
        metrics = PromMetrics(registry=CollectorRegistry())
        with pytest.raises(ValueError, match="must start with 'hr_'"):
            metrics.counter("bad_name", "desc")

    def test_counter_increments(self) -> None:
        metrics = PromMetrics(registry=CollectorRegistry())
        c = metrics.counter("hr_events_total", "count of events", labels=["kind"])
        c.labels(kind="asr").inc()
        c.labels(kind="asr").inc(2)
        # Prometheus client exposes internal samples via _value; use collect().
        samples = next(iter(c.collect())).samples
        matching = [
            s for s in samples if s.labels.get("kind") == "asr" and s.name.endswith("_total")
        ]
        assert matching[0].value == pytest.approx(3.0)

    def test_latency_histogram_registers(self) -> None:
        metrics = PromMetrics(registry=CollectorRegistry())
        h = metrics.latency_histogram("hr_asr_latency_ms", "asr latency in ms")
        h.observe(42.0)
        collected = list(h.collect())
        assert collected, "histogram should be registered"
