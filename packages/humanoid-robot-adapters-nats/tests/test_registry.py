"""Registry contract tests."""

from __future__ import annotations

import humanoid_robot.events as events_pkg
from humanoid_robot.adapters.nats.registry import SUBJECT_TO_EVENT


class TestRegistry:
    def test_registry_covers_all_events(self) -> None:
        # Every event class exported from humanoid_robot.events must be in
        # the registry, keyed by its subject.
        exported = [
            getattr(events_pkg, name)
            for name in events_pkg.__all__
            if isinstance(getattr(events_pkg, name), type)
            and issubclass(getattr(events_pkg, name), events_pkg.BaseEvent)
            and getattr(events_pkg, name) is not events_pkg.BaseEvent
        ]
        for cls in exported:
            assert SUBJECT_TO_EVENT[cls.subject] is cls, cls.__name__

    def test_no_extra_entries(self) -> None:
        subjects = {cls.subject for cls in SUBJECT_TO_EVENT.values()}
        assert subjects == set(SUBJECT_TO_EVENT.keys())
