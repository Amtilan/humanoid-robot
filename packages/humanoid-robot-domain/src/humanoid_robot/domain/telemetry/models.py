"""Telemetry domain — health and metric primitives."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.shared import Timestamp, utc_now


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthCheck(BaseModel):
    """A single component's health snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component: str
    status: HealthStatus
    detail: str | None = None
    observed_at: Timestamp = Field(default_factory=utc_now)


class MetricKind(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricSample(BaseModel):
    """One point-in-time metric observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: MetricKind
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    observed_at: Timestamp = Field(default_factory=utc_now)
