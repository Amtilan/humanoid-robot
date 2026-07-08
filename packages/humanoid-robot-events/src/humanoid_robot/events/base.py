"""Base event envelope.

Every published event is a subclass of `BaseEvent`. Fields are locked:
subclasses may add domain fields but never remove/reorder metadata fields.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.shared import CorrelationId, Timestamp, utc_now


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


class EventMetadata(BaseModel):
    """Non-payload metadata attached to every event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=_new_event_id)
    occurred_at: Timestamp = Field(default_factory=utc_now)
    correlation_id: CorrelationId
    causation_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    producer: str  # component name that emitted the event


class BaseEvent(BaseModel):
    """Base class for all platform events.

    Subclasses MUST set `subject` (NATS topic) and `schema_version` as
    class variables. Both are enforced at class-init time via
    `__init_subclass__`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: ClassVar[str]
    schema_version: ClassVar[int]

    meta: EventMetadata

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Forward to pydantic's __init_subclass__; typing there is stricter than
        # `object`, but we do not consume any of these kwargs ourselves.
        super().__init_subclass__(**kwargs)  # type: ignore[arg-type]
        if not getattr(cls, "subject", None):
            msg = f"{cls.__name__} must set class variable `subject`"
            raise TypeError(msg)
        if not getattr(cls, "schema_version", None):
            msg = f"{cls.__name__} must set class variable `schema_version`"
            raise TypeError(msg)
