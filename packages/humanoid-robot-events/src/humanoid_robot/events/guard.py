"""Security-desk (пункт охраны) events.

The robot interviews a visitor (ФИО → организация → цель → к кому →
пропуск → удостоверение); the completed card is announced on the bus so
cortex-core can persist it to the visit journal and the guard panel in
the dashboard updates live.
"""

from __future__ import annotations

from typing import ClassVar

from humanoid_robot.events.base import BaseEvent


class VisitIntakeStart(BaseEvent):
    """Ask the voice pipeline to begin the visitor interview (panel button,
    or later — the visitor-detection camera)."""

    subject: ClassVar[str] = "visit.intake.start"
    schema_version: ClassVar[int] = 1

    actor: str = "operator"


class VisitCardCompleted(BaseEvent):
    """A finished visitor card, confirmed by the visitor."""

    subject: ClassVar[str] = "visit.card.completed"
    schema_version: ClassVar[int] = 1

    language: str = "ru"
    full_name: str = ""
    organization: str = ""
    purpose: str = ""
    destination: str = ""
    # None = the visitor was not asked / gave no clear answer.
    has_pass: bool | None = None
    has_id: bool | None = None
