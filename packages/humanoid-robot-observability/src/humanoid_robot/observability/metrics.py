"""Thin Prometheus wrappers enforcing a common naming/labels policy.

Policy:
    - All metric names are lower_snake_case and prefixed with `hr_`.
    - Every metric declares its labels explicitly at construction; runtime
      label creation is not allowed (avoids cardinality explosions).
    - Histograms use buckets tuned for millisecond-scale AI latencies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

_MS_BUCKETS: tuple[float, ...] = (
    5,
    10,
    25,
    50,
    100,
    200,
    400,
    800,
    1_600,
    3_200,
    6_400,
    12_800,
)


@dataclass(slots=True)
class PromMetrics:
    """Facade for creating and looking up metrics with consistent policy."""

    registry: CollectorRegistry

    def counter(self, name: str, description: str, labels: Sequence[str] = ()) -> Counter:
        return Counter(
            _normalise(name),
            description,
            labelnames=tuple(labels),
            registry=self.registry,
        )

    def gauge(self, name: str, description: str, labels: Sequence[str] = ()) -> Gauge:
        return Gauge(
            _normalise(name),
            description,
            labelnames=tuple(labels),
            registry=self.registry,
        )

    def latency_histogram(
        self,
        name: str,
        description: str,
        labels: Sequence[str] = (),
    ) -> Histogram:
        return Histogram(
            _normalise(name),
            description,
            labelnames=tuple(labels),
            buckets=_MS_BUCKETS,
            registry=self.registry,
        )


def _normalise(name: str) -> str:
    if not name.startswith("hr_"):
        msg = f"metric name {name!r} must start with 'hr_'"
        raise ValueError(msg)
    return name
