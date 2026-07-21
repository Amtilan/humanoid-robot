"""WallCommandRelay: requested events reach the port and produce results."""

from __future__ import annotations

from humanoid_robot.core.wall_relay import WallCommandRelay
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.domain.wall import (
    WallCommand,
    WallCommandKind,
    WallCommandOutcome,
    WallCommandResult,
    WallSection,
)
from humanoid_robot.events import WallCommandRequested, WallCommandResulted
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.testing import InMemoryEventBus


class _FakeWall:
    def __init__(self, outcome: WallCommandOutcome) -> None:
        self.outcome = outcome
        self.sent: list[WallCommand] = []
        self.closed = False

    async def send(self, command: WallCommand) -> WallCommandResult:
        self.sent.append(command)
        return WallCommandResult(outcome=self.outcome)

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


def _requested(command: WallCommand) -> WallCommandRequested:
    return WallCommandRequested(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="test"),
        command_id="cmd-1",
        command=command,
        source="test",
    )


async def test_relay_executes_and_publishes_result() -> None:
    bus = InMemoryEventBus()
    wall = _FakeWall(WallCommandOutcome.ACCEPTED)
    relay = WallCommandRelay(bus=bus, wall=wall)
    await relay.start()

    command = WallCommand(kind=WallCommandKind.OPEN_SECTION, section=WallSection.AERO1)
    await bus.publish(_requested(command))

    assert wall.sent == [command]
    results = [e for e in bus.published if isinstance(e, WallCommandResulted)]
    assert len(results) == 1
    assert results[0].command_id == "cmd-1"
    assert results[0].result.outcome is WallCommandOutcome.ACCEPTED

    await relay.stop()
    assert wall.closed


async def test_relay_reports_unreachable() -> None:
    bus = InMemoryEventBus()
    wall = _FakeWall(WallCommandOutcome.UNREACHABLE)
    relay = WallCommandRelay(bus=bus, wall=wall)
    await relay.start()

    await bus.publish(
        _requested(WallCommand(kind=WallCommandKind.OPEN_SECTION, section=WallSection.JD1))
    )
    results = [e for e in bus.published if isinstance(e, WallCommandResulted)]
    assert results[0].result.outcome is WallCommandOutcome.UNREACHABLE
    await relay.stop()
