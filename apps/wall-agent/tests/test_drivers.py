def test_pipe_driver_maps_sections() -> None:
    from humanoid_robot.domain.wall import WallSection
    from humanoid_robot.wall_agent.drivers import _SECTION_TO_MENU, PipeWallDriver

    d = PipeWallDriver()
    assert d.name == "pipe"
    assert _SECTION_TO_MENU[WallSection.AERO1] == "MENU_AERO1"
    # Avto5 has no wall command — must be rejected, not sent.
    from humanoid_robot.domain.wall import WallCommand, WallCommandKind, WallCommandOutcome

    res = d.execute(WallCommand(kind=WallCommandKind.OPEN_SECTION, section=WallSection.AVTO5))
    assert res.outcome is WallCommandOutcome.REJECTED
    assert "no wall command" in (res.detail or "")


def test_pipe_driver_rejects_slide_nav() -> None:
    from humanoid_robot.domain.wall import (
        WallCommand,
        WallCommandKind,
        WallCommandOutcome,
        WallNavAction,
    )
    from humanoid_robot.wall_agent.drivers import PipeWallDriver

    d = PipeWallDriver()
    res = d.execute(WallCommand(kind=WallCommandKind.NAVIGATE, nav=WallNavAction.NEXT_SLIDE))
    assert res.outcome is WallCommandOutcome.REJECTED
