"""Tests for the event base envelope + version guards."""

from __future__ import annotations

from typing import ClassVar

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events.base import BaseEvent, EventMetadata


class _GoodEvent(BaseEvent):
    subject: ClassVar[str] = "test.good"
    schema_version: ClassVar[int] = 1

    payload: str


def _make_meta() -> EventMetadata:
    return EventMetadata(
        correlation_id=new_correlation_id(),
        producer="test-suite",
    )


class TestBaseEvent:
    def test_subject_required(self) -> None:
        with pytest.raises(TypeError, match="subject"):

            class _BadNoSubject(BaseEvent):
                schema_version: ClassVar[int] = 1

    def test_schema_version_required(self) -> None:
        with pytest.raises(TypeError, match="schema_version"):

            class _BadNoVersion(BaseEvent):
                subject: ClassVar[str] = "test.bad"

    def test_event_is_frozen(self) -> None:
        ev = _GoodEvent(meta=_make_meta(), payload="x")
        with pytest.raises(Exception):  # noqa: PT011,B017
            ev.payload = "y"  # type: ignore[misc]  # frozen model

    def test_metadata_has_defaults(self) -> None:
        meta = _make_meta()
        assert meta.event_id.startswith("evt_")
        assert meta.occurred_at.tzinfo is not None
        assert meta.producer == "test-suite"
