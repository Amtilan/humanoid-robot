"""Wall intent matcher — command matrix behaviour (RU/KZ, fuzzy, guards)."""

from __future__ import annotations

import pytest

from humanoid_robot.domain.voice import Language
from humanoid_robot.domain.wall import WallCommandKind, WallNavAction, WallSection
from humanoid_robot.rag.wall_intent import WallIntentMatcher, detect_language


@pytest.fixture(scope="module")
def matcher() -> WallIntentMatcher:
    return WallIntentMatcher()


@pytest.mark.parametrize(
    ("utterance", "section"),
    [
        ("Покажи Кызылорда — Жезказган", WallSection.AVTO1),
        ("покажи актобе карабутак улгайсын", WallSection.AVTO2),
        ("мост через Иртыш покажи пожалуйста", WallSection.AVTO3),
        ("Покажи обход Сарыагаша", WallSection.AVTO4),
        ("железная дорога Дарбаза Мактаарал", WallSection.JD1),
        ("Мойынты Кызылжар", WallSection.JD2),
        ("покажи Бахты Аягоз", WallSection.JD3),
        ("Покажи аэропорт Зайсан", WallSection.AERO1),
        ("аэропорт Катон-Карагай", WallSection.AERO2),
        ("покажи аэропорт Кендерли", WallSection.AERO3),
        ("открой аэропорт Аркалык", WallSection.AERO4),
    ],
)
def test_russian_sections(matcher: WallIntentMatcher, utterance: str, section: WallSection) -> None:
    match = matcher.match(utterance)
    assert match is not None, utterance
    assert match.command.kind is WallCommandKind.OPEN_SECTION
    assert match.command.section is section
    assert match.language is Language.RU
    assert match.speak


@pytest.mark.parametrize(
    ("utterance", "section"),
    [
        ("Қызылорда — Жезқазған көрсет", WallSection.AVTO1),
        ("Ертіс өзеніндегі көпір", WallSection.AVTO3),
        ("Зайсан әуежайы көрсет", WallSection.AERO1),
        ("Дарбаза — Мақтаарал темір жолы", WallSection.JD1),
    ],
)
def test_kazakh_sections(matcher: WallIntentMatcher, utterance: str, section: WallSection) -> None:
    match = matcher.match(utterance)
    assert match is not None, utterance
    assert match.command.section is section
    assert match.language is Language.KK
    assert match.speak  # Kazakh accompaniment


def test_fuzzy_tolerates_asr_noise(matcher: WallIntentMatcher) -> None:
    match = matcher.match("покажи кызылорда жесказган")  # ASR typo
    assert match is not None
    assert match.command.section is WallSection.AVTO1


@pytest.mark.parametrize(
    ("utterance", "action"),
    [
        ("главное меню", WallNavAction.MAIN_MENU),
        ("вернись в начало", WallNavAction.MAIN_MENU),
        ("следующий раздел", WallNavAction.NEXT_SECTION),
        ("предыдущий раздел", WallNavAction.PREV_SECTION),
        ("дальше", WallNavAction.NEXT_SLIDE),
        ("назад", WallNavAction.PREV_SLIDE),
    ],
)
def test_navigation(matcher: WallIntentMatcher, utterance: str, action: WallNavAction) -> None:
    match = matcher.match(utterance)
    assert match is not None, utterance
    assert match.command.kind is WallCommandKind.NAVIGATE
    assert match.command.nav is action


def test_category_opens_first_section(matcher: WallIntentMatcher) -> None:
    match = matcher.match("покажи аэропорты")
    assert match is not None
    assert match.command.section is WallSection.AERO1


def test_smalltalk_does_not_trigger(matcher: WallIntentMatcher) -> None:
    # Bare mention of a place without a "show" verb must not flip the wall.
    assert matcher.match("я вчера прилетел из Зайсана и немного устал") is None
    # Ordinary chat must not navigate.
    assert matcher.match("расскажи что ты умеешь делать и зачем ты здесь нужен") is None


def test_empty_and_neutral_text(matcher: WallIntentMatcher) -> None:
    assert matcher.match("") is None
    assert matcher.match("привет") is None


def test_detect_language() -> None:
    assert detect_language("Покажи мост") is Language.RU
    assert detect_language("көпірді көрсет") is Language.KK


def test_config_overrides(tmp_path: object) -> None:
    from pathlib import Path

    config = Path(str(tmp_path)) / "wall-intents.yaml"
    config.write_text(
        "sections:\n"
        "  Avto3:\n"
        '    aliases: ["паром через реку"]\n'
        '    speak_ru: "Текст заказчика."\n',
        encoding="utf-8",
    )
    matcher = WallIntentMatcher(config_path=str(config))
    match = matcher.match("покажи паром через реку")
    assert match is not None
    assert match.command.section is WallSection.AVTO3
    assert match.speak == "Текст заказчика."


def test_deadline_question_with_stroitelstvo_word() -> None:
    """«Когда завершат строительство X?» — вопрос о сроке, не о подрядчике."""
    from humanoid_robot.rag.presenter_kb import PresenterKb

    kb = PresenterKb(
        sections={
            "JD3": {
                "name_ru": "ЖД Бахты — Аягоз",
                "contractor_ru": "CHEC",
                "deadline_ru": "2027 год",
            }
        }
    )
    answer = kb.lookup("Когда завершат строительство ЖД Бахты Аягоз?")
    assert answer is not None
    assert "2027" in answer
