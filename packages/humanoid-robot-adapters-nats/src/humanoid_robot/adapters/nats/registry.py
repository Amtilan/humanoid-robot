"""Event class registry — maps NATS subjects to the event classes that own them.

Built at import time from `humanoid_robot.events.__all__`. Wildcards on the
producer side are not supported (an event has exactly one class); on the
consumer side wildcards are fine — we look up the incoming `msg.subject`.
"""

from __future__ import annotations

from typing import Final

import humanoid_robot.events as events_pkg
from humanoid_robot.events import BaseEvent


def _build() -> dict[str, type[BaseEvent]]:
    registry: dict[str, type[BaseEvent]] = {}
    for name in events_pkg.__all__:
        obj = getattr(events_pkg, name)
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, BaseEvent) or obj is BaseEvent:
            continue
        subject = obj.subject
        if subject in registry and registry[subject] is not obj:
            existing = registry[subject].__name__
            msg = (
                f"duplicate subject {subject!r}: {existing} and {obj.__name__}"
                " — subjects must be unique per event class"
            )
            raise RuntimeError(msg)
        registry[subject] = obj
    return registry


SUBJECT_TO_EVENT: Final[dict[str, type[BaseEvent]]] = _build()
