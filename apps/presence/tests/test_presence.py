"""Presence detection: motion scoring + one-event-per-visit state machine."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from humanoid_robot.events import VisitorDetected
from humanoid_robot.presence.detector import MotionDetector
from humanoid_robot.presence.runner import PresenceRunner
from humanoid_robot.testing import InMemoryEventBus


def _jpeg(brightness: int, box: tuple[int, int, int, int] | None = None) -> bytes:
    """A flat gray frame, optionally with a bright rectangle (the "visitor")."""
    frame = np.full((240, 320), brightness, dtype=np.uint8)
    if box is not None:
        x0, y0, x1, y1 = box
        frame[y0:y1, x0:x1] = 255
    buffer = io.BytesIO()
    Image.fromarray(frame, mode="L").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_detector_scores_change_not_stillness() -> None:
    detector = MotionDetector()
    assert detector.score(_jpeg(100)) == 0.0  # first frame: no reference yet
    assert detector.score(_jpeg(100)) < 0.005  # static scene ≈ 0
    assert detector.score(_jpeg(100, box=(40, 40, 200, 200))) > 0.05  # visitor


class _Frames:
    def __init__(self, frames: list[bytes]) -> None:
        self._frames = frames
        self._index = 0

    async def __call__(self) -> bytes | None:
        frame = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1
        return frame


async def test_one_event_per_visit_with_rearm() -> None:
    bus = InMemoryEventBus()
    clock_value = [0.0]

    quiet = _jpeg(100)
    visitor = _jpeg(100, box=(40, 40, 200, 200))
    gone = _jpeg(100)
    # quiet baseline → visitor walks in (2 frames) → stays → leaves → quiet → new visitor
    sequence = [
        quiet,
        quiet,
        visitor,
        quiet,
        visitor,
        quiet,
        *([gone] * 12),
        visitor,
        quiet,
        visitor,
    ]

    runner = PresenceRunner(
        bus=bus,
        frames=_Frames(sequence),
        threshold=0.02,
        trigger_frames=2,
        clear_frames=5,
        rearm_s=10.0,
        clock=lambda: clock_value[0],
    )

    for _ in range(6):
        await runner.step()
    events = [e for e in bus.published if isinstance(e, VisitorDetected)]
    assert len(events) == 1  # visitor moving around ≠ new visitor
    assert runner.present

    # Scene goes quiet, but before rearm_s no re-arm happens.
    for _ in range(6):
        await runner.step()
    assert runner.present  # rearm blocked by time, not only frames

    clock_value[0] = 60.0  # long past rearm_s
    for _ in range(6):
        await runner.step()
    assert not runner.present

    # Next visitor triggers a second event.
    for _ in range(3):
        await runner.step()
    events = [e for e in bus.published if isinstance(e, VisitorDetected)]
    assert len(events) == 2


async def test_camera_outage_is_quiet() -> None:
    bus = InMemoryEventBus()

    async def no_frames() -> bytes | None:
        return None

    runner = PresenceRunner(bus=bus, frames=no_frames)
    for _ in range(5):
        await runner.step()
    assert not bus.published
    assert not runner.present
