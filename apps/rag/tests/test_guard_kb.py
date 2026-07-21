"""Guard knowledge base — deterministic navigation + prompt block."""

from __future__ import annotations

from pathlib import Path

from humanoid_robot.rag.guard_kb import GuardKb

_SAMPLE = """
rooms:
  - room: "305"
    floor: "третий этаж"
    unit: "Управление цифровизации"
  - room: "203"
    floor: "второй этаж"
    unit: "Отдел кадров"
    note: "напротив лестницы"
faq:
  - q: "Режим работы"
    a: "С 9 до 18:30."
info: |
  Приём по записи.
"""


def _kb(tmp_path: Path) -> GuardKb:
    path = tmp_path / "kb.yaml"
    path.write_text(_SAMPLE, encoding="utf-8")
    return GuardKb.load(path)


class TestGuardKb:
    def test_room_lookup(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path)
        answer = kb.lookup("Подскажите, где кабинет 305?")
        assert answer is not None
        assert "третий этаж" in answer

    def test_unknown_room_refers_to_guard(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path)
        answer = kb.lookup("где кабинет 999")
        assert answer is not None
        assert "сотрудника охраны" in answer

    def test_unit_lookup(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path)
        answer = kb.lookup("Где находится отдел кадров?")
        assert answer is not None
        assert "203" in answer
        assert "второй этаж" in answer

    def test_non_navigation_returns_none(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path)
        assert kb.lookup("Какая сегодня погода?") is None

    def test_reference_block_contains_everything(self, tmp_path: Path) -> None:
        kb = _kb(tmp_path)
        block = kb.reference_block()
        assert "СПРАВКА" in block
        assert "Режим работы" in block
        assert "кабинет 305" in block
        assert "Приём по записи." in block

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        kb = GuardKb.load(tmp_path / "absent.yaml")
        assert kb.empty
        assert kb.lookup("где кабинет 305") is None
        assert kb.reference_block() == ""
