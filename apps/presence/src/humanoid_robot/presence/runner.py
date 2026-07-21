"""Presence runner — poll snapshots, detect a visitor, publish once per visit.

State machine with hysteresis:

    quiet --(score >= threshold for `trigger_frames` in a row)--> present
      ^                                                             |
      +--(score < threshold for `clear_frames` in a row,            |
          and at least `rearm_s` since the trigger)-----------------+

``visitor.detected`` fires exactly on the quiet→present transition, so one
visitor standing in front of the robot produces one event, not a stream.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import VisitorDetected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort
from humanoid_robot.presence.detector import MotionDetector

_LOG = get_logger("cortex-presence.runner")

FrameSource = Callable[[], Awaitable[bytes | None]]


class PresenceRunner:
    """Long-running detection loop over an async frame source."""

    def __init__(
        self,
        *,
        bus: EventBusPort,
        frames: FrameSource,
        detector: MotionDetector | None = None,
        threshold: float = 0.02,
        trigger_frames: int = 2,
        clear_frames: int = 10,
        rearm_s: float = 30.0,
        interval_s: float = 0.5,
        producer: str = "cortex-presence",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._frames = frames
        self._detector = detector or MotionDetector()
        self._threshold = threshold
        self._trigger_frames = trigger_frames
        self._clear_frames = clear_frames
        self._rearm_s = rearm_s
        self._interval_s = interval_s
        self._producer = producer
        self._clock = clock
        self._stop = asyncio.Event()
        # State.
        self.present = False
        self._active_streak = 0
        self._quiet_streak = 0
        self._triggered_at = 0.0

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        _LOG.info(
            "presence.ready",
            threshold=self._threshold,
            interval_s=self._interval_s,
            rearm_s=self._rearm_s,
        )
        while not self._stop.is_set():
            await self.step()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)
            except TimeoutError:
                continue

    async def step(self) -> None:
        """One poll+score+transition cycle (extracted for tests)."""
        frame = await self._frames()
        if frame is None:
            # Camera unavailable — treat as quiet, keep polling.
            self._detector.reset()
            return
        score = self._detector.score(frame)
        if score >= self._threshold:
            self._active_streak += 1
            self._quiet_streak = 0
        else:
            self._quiet_streak += 1
            self._active_streak = 0
        if not self.present and self._active_streak >= self._trigger_frames:
            self.present = True
            self._triggered_at = self._clock()
            _LOG.info("presence.visitor_detected", score=round(score, 4))
            await self._bus.publish(
                VisitorDetected(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self._producer,
                    ),
                    score=min(score, 1.0),
                )
            )
        elif (
            self.present
            and self._quiet_streak >= self._clear_frames
            and self._clock() - self._triggered_at >= self._rearm_s
        ):
            self.present = False
            _LOG.info("presence.rearmed")
