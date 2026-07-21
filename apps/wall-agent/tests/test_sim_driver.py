"""SimWallDriver state-machine behaviour."""

from __future__ import annotations

from humanoid_robot.domain.wall import (
    WallCommand,
    WallCommandKind,
    WallCommandOutcome,
    WallNavAction,
    WallSection,
)
from humanoid_robot.wall_agent.drivers import SimWallDriver


def _open(section: WallSection) -> WallCommand:
    return WallCommand(kind=WallCommandKind.OPEN_SECTION, section=section)


def _nav(action: WallNavAction) -> WallCommand:
    return WallCommand(kind=WallCommandKind.NAVIGATE, nav=action)


def test_open_section_switches_screen() -> None:
    driver = SimWallDriver()
    result = driver.execute(_open(WallSection.AERO1))
    assert result.outcome is WallCommandOutcome.ACCEPTED
    assert driver.state()["screen"] == "Aero1"
    assert driver.state()["slide"] == 0


def test_main_menu_resets() -> None:
    driver = SimWallDriver()
    driver.execute(_open(WallSection.JD2))
    driver.execute(_nav(WallNavAction.MAIN_MENU))
    assert driver.state()["screen"] == "Main"


def test_slides_move_within_section_only() -> None:
    driver = SimWallDriver()
    rejected = driver.execute(_nav(WallNavAction.NEXT_SLIDE))
    assert rejected.outcome is WallCommandOutcome.REJECTED

    driver.execute(_open(WallSection.AVTO3))
    driver.execute(_nav(WallNavAction.NEXT_SLIDE))
    driver.execute(_nav(WallNavAction.NEXT_SLIDE))
    assert driver.state()["slide"] == 2
    driver.execute(_nav(WallNavAction.PREV_SLIDE))
    assert driver.state()["slide"] == 1
    driver.execute(_nav(WallNavAction.PREV_SLIDE))
    driver.execute(_nav(WallNavAction.PREV_SLIDE))
    assert driver.state()["slide"] == 0  # clamped at zero


def test_next_section_wraps_within_category() -> None:
    driver = SimWallDriver()
    driver.execute(_open(WallSection.JD3))
    driver.execute(_nav(WallNavAction.NEXT_SECTION))
    assert driver.state()["screen"] == "JD1"  # wrapped, stayed in category
    driver.execute(_nav(WallNavAction.PREV_SECTION))
    assert driver.state()["screen"] == "JD3"


def test_section_nav_requires_open_section() -> None:
    driver = SimWallDriver()
    result = driver.execute(_nav(WallNavAction.NEXT_SECTION))
    assert result.outcome is WallCommandOutcome.REJECTED
