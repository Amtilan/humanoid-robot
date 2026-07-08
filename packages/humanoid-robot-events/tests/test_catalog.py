"""Contract tests: every published event has a unique subject and a schema."""

from __future__ import annotations

import humanoid_robot.events as events


def _all_event_classes() -> list[type[events.BaseEvent]]:
    return [
        cls
        for name in events.__all__
        if isinstance(cls := getattr(events, name), type) and issubclass(cls, events.BaseEvent)
        if cls is not events.BaseEvent
    ]


class TestEventCatalog:
    def test_every_event_declares_subject_and_version(self) -> None:
        classes = _all_event_classes()
        assert classes, "no event subclasses discovered from `humanoid_robot.events`"
        for cls in classes:
            assert cls.subject, f"{cls.__name__} has empty subject"
            assert cls.schema_version >= 1, f"{cls.__name__} has invalid version"

    def test_subjects_are_unique(self) -> None:
        subjects = [cls.subject for cls in _all_event_classes()]
        duplicates = {s for s in subjects if subjects.count(s) > 1}
        assert not duplicates, f"duplicate event subjects: {duplicates}"

    def test_json_schema_export_shape(self) -> None:
        # Every event must produce a valid JSON schema.
        for cls in _all_event_classes():
            schema = cls.model_json_schema()
            assert schema["type"] == "object"
            assert "properties" in schema
