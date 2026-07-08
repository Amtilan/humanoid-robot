"""System-level events (lifecycle, OTA, audit)."""

from __future__ import annotations

from typing import ClassVar

from humanoid_robot.domain.telemetry import HealthStatus
from humanoid_robot.events.base import BaseEvent


class SystemReady(BaseEvent):
    """All required capabilities are online."""

    subject: ClassVar[str] = "system.ready"
    schema_version: ClassVar[int] = 1

    components: tuple[str, ...]


class SystemShuttingDown(BaseEvent):
    """The platform is entering graceful shutdown."""

    subject: ClassVar[str] = "system.shutting_down"
    schema_version: ClassVar[int] = 1

    reason: str


class SystemHealth(BaseEvent):
    """A component's health status changed."""

    subject: ClassVar[str] = "system.health"
    schema_version: ClassVar[int] = 1

    component: str
    status: HealthStatus
    detail: str | None = None


class OtaAvailable(BaseEvent):
    """A new update is available for install."""

    subject: ClassVar[str] = "system.ota.available"
    schema_version: ClassVar[int] = 1

    release_id: str
    version: str
    notes: str | None = None


class OtaApplied(BaseEvent):
    """An OTA installation finished (may be success or failure)."""

    subject: ClassVar[str] = "system.ota.applied"
    schema_version: ClassVar[int] = 1

    release_id: str
    success: bool
    rolled_back: bool = False
    detail: str | None = None


class SecurityAudit(BaseEvent):
    """An access-control decision worth persisting."""

    subject: ClassVar[str] = "security.audit"
    schema_version: ClassVar[int] = 1

    actor: str
    action: str
    resource: str
    allowed: bool
    detail: str | None = None
