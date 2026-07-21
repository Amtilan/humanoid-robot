"""Visitor-interview state machine (пункт охраны)."""

from __future__ import annotations

from humanoid_robot.rag.visit_intake import VisitIntake, wants_intake


def _run_happy_path(intake: VisitIntake) -> dict[str, object]:
    intake.start()
    replies = []
    for answer in (
        "Иванов Иван Иванович",
        "ТОО Транспорт Сервис",
        "Подписание договора",
        "К начальнику отдела кадров",
        "Да",
        "Да, с собой",
    ):
        reply, card = intake.consume(answer)
        replies.append(reply)
        assert card is None
    assert "Всё верно?" in replies[-1]
    reply, card = intake.consume("да, всё верно")
    assert card is not None
    assert "передал" in reply
    return card


class TestVisitIntake:
    def test_happy_path_collects_all_fields(self) -> None:
        card = _run_happy_path(VisitIntake())
        assert card["full_name"] == "Иванов Иван Иванович"
        assert card["organization"] == "ТОО Транспорт Сервис"
        assert card["purpose"] == "Подписание договора"
        assert card["destination"] == "К начальнику отдела кадров"
        assert card["has_pass"] is True
        assert card["has_id"] is True

    def test_disengages_after_completion(self) -> None:
        intake = VisitIntake()
        _run_happy_path(intake)
        assert intake.engaged is False
        reply, card = intake.consume("что-то ещё")
        assert reply == ""
        assert card is None

    def test_no_answers_parsed_as_false(self) -> None:
        intake = VisitIntake()
        intake.start()
        for answer in ("Петров Пётр", "Частное лицо", "Консультация", "В приёмную"):
            intake.consume(answer)
        intake.consume("нет")
        reply, _ = intake.consume("нету")
        assert "пропуск: нет" in reply
        assert "удостоверение: нет" in reply

    def test_unclear_yes_no_reasks(self) -> None:
        intake = VisitIntake()
        intake.start()
        for answer in ("Сидоров", "ТОО Ромашка", "Встреча", "Отдел кадров"):
            intake.consume(answer)
        reply, card = intake.consume("ну как вам сказать")
        assert card is None
        assert "да или нет" in reply

    def test_cancel_mid_interview(self) -> None:
        intake = VisitIntake()
        intake.start()
        intake.consume("Иванов")
        reply, card = intake.consume("отмена")
        assert card is None
        assert "отменено" in reply
        assert intake.engaged is False

    def test_confirmation_no_restarts(self) -> None:
        intake = VisitIntake()
        intake.start()
        for answer in ("Иванов", "ТОО", "Встреча", "Приёмная", "да", "да"):
            intake.consume(answer)
        reply, card = intake.consume("нет, неверно")
        assert card is None
        assert "заново" in reply
        assert intake.engaged is True

    def test_trigger_phrases(self) -> None:
        assert wants_intake("Я хочу оформить визит")
        assert wants_intake("зарегистрируйте меня, пожалуйста")
        assert wants_intake("я посетитель")
        assert not wants_intake("какая сегодня погода")
