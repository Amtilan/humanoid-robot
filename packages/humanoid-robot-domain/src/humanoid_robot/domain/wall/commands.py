"""Domain model for the presentation video wall (MinTrans application).

The wall application exposes 12 presentation sections in three categories.
Section identifiers match the application's own screen/folder names
(``Datas/<section>``), so no translation layer is needed downstream.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class WallSection(StrEnum):
    """A presentation section (screen) of the wall application."""

    AVTO1 = "Avto1"
    AVTO2 = "Avto2"
    AVTO3 = "Avto3"
    AVTO4 = "Avto4"
    AVTO5 = "Avto5"
    JD1 = "JD1"
    JD2 = "JD2"
    JD3 = "JD3"
    AERO1 = "Aero1"
    AERO2 = "Aero2"
    AERO3 = "Aero3"
    AERO4 = "Aero4"


class WallCategory(StrEnum):
    """Section category shown in the wall application's main menu."""

    AVTO = "avto"
    JD = "jd"
    AERO = "aero"


WALL_CATEGORY_SECTIONS: dict[WallCategory, tuple[WallSection, ...]] = {
    WallCategory.AVTO: (
        WallSection.AVTO1,
        WallSection.AVTO2,
        WallSection.AVTO3,
        WallSection.AVTO4,
        WallSection.AVTO5,
    ),
    WallCategory.JD: (WallSection.JD1, WallSection.JD2, WallSection.JD3),
    WallCategory.AERO: (
        WallSection.AERO1,
        WallSection.AERO2,
        WallSection.AERO3,
        WallSection.AERO4,
    ),
}


class WallNavAction(StrEnum):
    """Navigation actions that do not target a specific section."""

    MAIN_MENU = "main_menu"
    NEXT_SECTION = "next_section"
    PREV_SECTION = "prev_section"
    NEXT_SLIDE = "next_slide"
    PREV_SLIDE = "prev_slide"


class WallCommandKind(StrEnum):
    """Discriminates the two shapes of a wall command."""

    OPEN_SECTION = "open_section"
    NAVIGATE = "navigate"


class WallCommand(BaseModel):
    """A single command for the wall-control agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: WallCommandKind
    section: WallSection | None = None
    nav: WallNavAction | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> WallCommand:
        if self.kind is WallCommandKind.OPEN_SECTION and self.section is None:
            msg = "open_section command requires a section"
            raise ValueError(msg)
        if self.kind is WallCommandKind.NAVIGATE and self.nav is None:
            msg = "navigate command requires a nav action"
            raise ValueError(msg)
        return self


class WallCommandOutcome(StrEnum):
    """Terminal state of a wall command."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNREACHABLE = "unreachable"


class WallCommandResult(BaseModel):
    """Result reported by the wall-control agent (or the HTTP client)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: WallCommandOutcome
    detail: str = ""
