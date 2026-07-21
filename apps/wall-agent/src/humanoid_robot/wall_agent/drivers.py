"""Wall drivers — the pluggable backends that actually switch the wall app.

``SimWallDriver`` models the MinTrans application in memory (used for
autonomous testing and CI). ``SendInputWallDriver`` emulates keyboard/mouse
input on the Windows PC that runs the real application.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from humanoid_robot.domain.wall import (
    WALL_CATEGORY_SECTIONS,
    WallCategory,
    WallCommand,
    WallCommandKind,
    WallCommandOutcome,
    WallCommandResult,
    WallNavAction,
    WallSection,
)

log = logging.getLogger(__name__)

_MAIN_SCREEN = "Main"
_MAX_SLIDE = 99


class WallDriver(Protocol):
    """A backend that executes wall commands."""

    name: str

    def execute(self, command: WallCommand) -> WallCommandResult:
        """Apply one command to the wall application."""
        ...

    def state(self) -> dict[str, Any]:
        """Best-effort view of the wall application's current state."""
        ...


def _section_category(section: WallSection) -> WallCategory:
    for category, sections in WALL_CATEGORY_SECTIONS.items():
        if section in sections:
            return category
    msg = f"section {section} is not in any category"  # pragma: no cover
    raise ValueError(msg)  # pragma: no cover


class SimWallDriver:
    """In-memory model of the wall application.

    Mirrors what the real app does: one main menu, 12 section screens, and a
    slide sequence inside each section (PgUp/PgDn in the real app).
    """

    name = "sim"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._screen: str = _MAIN_SCREEN
        self._slide = 0
        self.history: list[WallCommand] = []

    def execute(self, command: WallCommand) -> WallCommandResult:
        with self._lock:
            self.history.append(command)
            if command.kind is WallCommandKind.OPEN_SECTION:
                assert command.section is not None  # noqa: S101 — validated model
                self._screen = command.section.value
                self._slide = 0
                log.info("sim: open section %s", command.section.value)
                return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)
            assert command.nav is not None  # noqa: S101 — validated model
            return self._navigate(command.nav)

    def _navigate(self, nav: WallNavAction) -> WallCommandResult:
        if nav is WallNavAction.MAIN_MENU:
            self._screen = _MAIN_SCREEN
            self._slide = 0
            log.info("sim: main menu")
            return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)
        if nav in (WallNavAction.NEXT_SLIDE, WallNavAction.PREV_SLIDE):
            if self._screen == _MAIN_SCREEN:
                return WallCommandResult(
                    outcome=WallCommandOutcome.REJECTED,
                    detail="no section open",
                )
            step = 1 if nav is WallNavAction.NEXT_SLIDE else -1
            self._slide = min(max(self._slide + step, 0), _MAX_SLIDE)
            log.info("sim: slide -> %d", self._slide)
            return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)
        # next_section / prev_section — wrap within the current category.
        if self._screen == _MAIN_SCREEN:
            return WallCommandResult(
                outcome=WallCommandOutcome.REJECTED,
                detail="no section open",
            )
        current = WallSection(self._screen)
        sections = WALL_CATEGORY_SECTIONS[_section_category(current)]
        index = sections.index(current)
        step = 1 if nav is WallNavAction.NEXT_SECTION else -1
        target = sections[(index + step) % len(sections)]
        self._screen = target.value
        self._slide = 0
        log.info("sim: section -> %s", target.value)
        return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {"screen": self._screen, "slide": self._slide, "exact": True}


# --- Windows input emulation ------------------------------------------------

# Virtual-key codes for the subset of keys the wall app / mapping may use.
_VIRTUAL_KEYS: dict[str, int] = {
    "pgup": 0x21,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "enter": 0x0D,
    "esc": 0x1B,
    "space": 0x20,
    "tab": 0x09,
    **{chr(c): c - 0x20 for c in range(ord("a"), ord("z") + 1)},  # a-z -> A-Z VK
    **{chr(c): c for c in range(ord("0"), ord("9") + 1)},
}

_KEYEVENTF_KEYUP = 0x0002
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_MOVE = 0x0001
_ABSOLUTE_RANGE = 65535
_DEFAULT_STEP_DELAY_S = 0.15


class SendInputWallDriver:
    """Drives the real wall app on Windows via input emulation.

    The action map is a JSON file calibrated on-site::

        {
            "window_title": "Factories",
            "actions": {
                "open_section:Avto1": [{"click": [0.25, 0.40]}],
                "navigate:main_menu": [{"click": [0.03, 0.05]}],
                "navigate:next_slide": [{"key": "pgdn"}],
                "navigate:prev_slide": [{"key": "pgup"}],
            },
        }

    Each action list is replayed in order; entries are ``{"key": name}``,
    ``{"click": [nx, ny]}`` (normalized 0..1 screen coordinates) and
    ``{"sleep": milliseconds}``.
    """

    name = "sendinput"

    def __init__(self, mapping_path: str) -> None:
        import sys

        if sys.platform != "win32":  # pragma: no cover — exercised on Windows only
            msg = "sendinput driver requires Windows"
            raise RuntimeError(msg)
        raw = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        self._window_title: str = raw.get("window_title", "Factories")
        self._actions: dict[str, list[dict[str, Any]]] = raw.get("actions", {})
        self._step_delay_s: float = raw.get("step_delay_s", _DEFAULT_STEP_DELAY_S)
        self._lock = threading.Lock()
        self._screen = "unknown"

    # The whole class below touches user32 via ctypes and only ever runs on
    # Windows; coverage and unit tests exercise SimWallDriver instead.

    def _user32(self) -> Any:  # pragma: no cover
        import ctypes

        return ctypes.windll.user32  # type: ignore[attr-defined]

    def _focus_window(self) -> bool:  # pragma: no cover
        user32 = self._user32()
        handle = user32.FindWindowW(None, self._window_title)
        if not handle:
            return False
        user32.ShowWindow(handle, 9)  # SW_RESTORE
        user32.SetForegroundWindow(handle)
        time.sleep(0.2)
        return True

    def _press_key(self, name: str) -> None:  # pragma: no cover
        code = _VIRTUAL_KEYS[name.lower()]
        user32 = self._user32()
        user32.keybd_event(code, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(code, 0, _KEYEVENTF_KEYUP, 0)

    def _click(self, nx: float, ny: float) -> None:  # pragma: no cover
        user32 = self._user32()
        x = int(nx * _ABSOLUTE_RANGE)
        y = int(ny * _ABSOLUTE_RANGE)
        user32.mouse_event(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, x, y, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def execute(self, command: WallCommand) -> WallCommandResult:  # pragma: no cover
        key = (
            f"open_section:{command.section.value}"
            if command.kind is WallCommandKind.OPEN_SECTION and command.section
            else f"navigate:{command.nav.value if command.nav else ''}"
        )
        actions = self._actions.get(key)
        if actions is None:
            return WallCommandResult(
                outcome=WallCommandOutcome.REJECTED,
                detail=f"no mapping for {key!r}",
            )
        with self._lock:
            if not self._focus_window():
                return WallCommandResult(
                    outcome=WallCommandOutcome.REJECTED,
                    detail=f"window {self._window_title!r} not found",
                )
            for action in actions:
                if "key" in action:
                    self._press_key(str(action["key"]))
                elif "click" in action:
                    nx, ny = action["click"]
                    self._click(float(nx), float(ny))
                elif "sleep" in action:
                    time.sleep(float(action["sleep"]) / 1000.0)
                time.sleep(self._step_delay_s)
            if command.kind is WallCommandKind.OPEN_SECTION and command.section:
                self._screen = command.section.value
            elif command.nav is WallNavAction.MAIN_MENU:
                self._screen = _MAIN_SCREEN
        return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)

    def state(self) -> dict[str, Any]:  # pragma: no cover
        with self._lock:
            return {"screen": self._screen, "slide": None, "exact": False}


def build_driver(name: str, *, mapping_path: str | None = None) -> WallDriver:
    """Factory used by the CLI entrypoint."""
    if name == "sim":
        return SimWallDriver()
    if name == "sendinput":
        if not mapping_path:
            msg = "sendinput driver requires --mapping <file.json>"
            raise ValueError(msg)
        return SendInputWallDriver(mapping_path)
    msg = f"unknown wall driver {name!r}"
    raise ValueError(msg)
