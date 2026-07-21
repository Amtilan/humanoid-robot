"""Voice → video-wall intent matching (the presenter's command matrix).

Deterministic fast path: navigation and «покажи раздел X» phrases are matched
here — in both Russian and Kazakh — and turned into ``WallCommand``s without
ever calling the LLM, so the wall reacts instantly.

Matching strategy:
    - the utterance is normalized (casefold, ё→е, Kazakh-specific letters
      folded onto their Russian lookalikes, punctuation stripped) so one
      alias list covers RU and KZ variants of the same proper name;
    - a section alias matches when ALL of its significant words occur in the
      utterance (fuzzy per-word comparison forgives small ASR errors);
    - one-word aliases additionally require a "show" verb («покажи»,
      «открой», «көрсет»…) so a passing mention of a city does not flip the
      wall;
    - navigation aliases only match short utterances (a command, not a
      story).

The built-in matrix mirrors the approved command matrix (plan §5); the
customer's final texts override it via a YAML file (``config_path``).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from humanoid_robot.domain.voice import Language
from humanoid_robot.domain.wall import (
    WallCommand,
    WallCommandKind,
    WallNavAction,
    WallSection,
)

# Kazakh-specific letters folded to Russian lookalikes so «Қызылорда» and
# «Кызылорда» normalize identically.
_KZ_FOLD = str.maketrans(
    {
        "қ": "к",
        "ғ": "г",
        "ң": "н",
        "ә": "а",
        "ө": "о",
        "ұ": "у",
        "ү": "у",
        "һ": "х",
        "і": "и",
    }
)

_KZ_CHARS = set("қғңәөұүһі")
_WORD_RE = re.compile(r"[а-яa-z0-9]+")
_FUZZY_CUTOFF = 0.8
_MAX_NAV_WORDS = 5

_SHOW_VERBS = frozenset(
    {
        "покажи",
        "покажите",
        "открой",
        "откройте",
        "запусти",
        "запустите",
        "включи",
        "включите",
        "корсет",  # көрсет(іңіз) folded
        "корсетиниз",
        "аш",
        "ашыныз",
    }
)


def detect_language(text: str) -> Language:
    """KZ when the utterance uses Kazakh-specific letters, RU otherwise."""
    lowered = text.lower()
    if any(ch in _KZ_CHARS for ch in lowered):
        return Language.KK
    return Language.RU


def _normalize(text: str) -> list[str]:
    lowered = text.lower().replace("ё", "е").translate(_KZ_FOLD)
    return _WORD_RE.findall(lowered)


def _word_in(word: str, words: list[str]) -> bool:
    if word in words:
        return True
    return bool(difflib.get_close_matches(word, words, n=1, cutoff=_FUZZY_CUTOFF))


@dataclass(frozen=True, slots=True)
class WallIntentMatch:
    """A recognised wall command plus the line the robot should say."""

    command: WallCommand
    speak: str
    language: Language


@dataclass(frozen=True, slots=True)
class _SectionRule:
    section: WallSection
    aliases: tuple[tuple[str, ...], ...]  # each alias = words that must all occur
    speak_ru: str
    speak_kz: str


# --- Built-in matrix (plan §5; customer texts override via YAML) -------------

_DEFAULT_SECTIONS: tuple[_SectionRule, ...] = (
    _SectionRule(
        WallSection.AVTO1,
        (("кызылорда", "жезказган"),),
        "Сейчас на экране — автодорога Кызылорда — Жезказган.",
        "Қазір экранда — Қызылорда — Жезқазған автожолы.",
    ),
    _SectionRule(
        WallSection.AVTO2,
        (("актобе", "карабутак"), ("карабутак", "улгайсын")),
        "Сейчас на экране — автодорога Актобе — Карабутак — Улгайсын.",
        "Қазір экранда — Ақтөбе — Қарабұтақ — Ұлғайсын автожолы.",
    ),
    _SectionRule(
        WallSection.AVTO3,
        (("мост", "иртыш"), ("копир", "ертис")),
        "Сейчас на экране — строительство моста через реку Иртыш.",
        "Қазір экранда — Ертіс өзені арқылы көпір құрылысы.",
    ),
    _SectionRule(
        WallSection.AVTO4,
        (("обход", "сарыагаш"), ("сарыагаш",)),
        "Сейчас на экране — обход города Сарыагаш.",
        "Қазір экранда — Сарыағаш қаласын айналып өту жолы.",
    ),
    _SectionRule(
        WallSection.AVTO5,
        (("актобе", "улгайсын"),),
        "Сейчас на экране — автодорога Актобе — Улгайсын.",
        "Қазір экранда — Ақтөбе — Ұлғайсын автожолы.",
    ),
    _SectionRule(
        WallSection.JD1,
        (("дарбаза", "мактаарал"), ("дарбаза",), ("мактаарал",)),
        "Сейчас на экране — железнодорожная линия Дарбаза — Мактаарал.",
        "Қазір экранда — Дарбаза — Мақтаарал темір жол желісі.",
    ),
    _SectionRule(
        WallSection.JD2,
        (("мойынты", "кызылжар"), ("мойынты",), ("кызылжар",)),
        "Сейчас на экране — железнодорожная линия Мойынты — Кызылжар.",
        "Қазір экранда — Мойынты — Қызылжар темір жол желісі.",
    ),
    _SectionRule(
        WallSection.JD3,
        (("бахты", "аягоз"), ("бахты",), ("аягоз",)),
        "Сейчас на экране — железнодорожная линия Бахты — Аягоз.",
        "Қазір экранда — Бақты — Аягөз темір жол желісі.",
    ),
    _SectionRule(
        WallSection.AERO1,
        (("аэропорт", "зайсан"), ("зайсан",), ("ауежай", "зайсан")),
        "Сейчас на экране — строительство аэропорта Зайсан.",
        "Қазір экранда — Зайсан әуежайының құрылысы.",
    ),
    _SectionRule(
        WallSection.AERO2,
        (("катон", "карагай"), ("катонкарагай",)),
        "Сейчас на экране — строительство аэропорта Катон-Карагай.",
        "Қазір экранда — Катонқарағай әуежайының құрылысы.",
    ),
    _SectionRule(
        WallSection.AERO3,
        (("аэропорт", "кендерли"), ("кендерли",), ("кендирли",)),
        "Сейчас на экране — строительство аэропорта Кендерли.",
        "Қазір экранда — Кендірлі әуежайының құрылысы.",
    ),
    _SectionRule(
        WallSection.AERO4,
        (("аэропорт", "аркалык"), ("аркалык",)),
        "Сейчас на экране — возобновление деятельности аэропорта Аркалык.",
        "Қазір экранда — Арқалық әуежайының қызметін қалпына келтіру.",
    ),
)

_CATEGORY_ALIASES: tuple[tuple[WallSection, tuple[str, ...], str, str], ...] = (
    (
        WallSection.AVTO1,
        ("автодороги", "автодорог", "дороги", "автожол", "автожолдар"),
        "Открываю раздел автодорог.",
        "Автожолдар бөлімін ашамын.",
    ),
    (
        WallSection.JD1,
        ("железные", "железных", "темир"),
        "Открываю раздел железных дорог.",
        "Темір жолдар бөлімін ашамын.",
    ),
    (
        WallSection.AERO1,
        ("аэропорты", "аэропортов", "ауежайлар"),
        "Открываю раздел аэропортов.",
        "Әуежайлар бөлімін ашамын.",
    ),
)

_NAV_RULES: tuple[tuple[WallNavAction, tuple[str, ...], str, str], ...] = (
    (
        WallNavAction.MAIN_MENU,
        ("главное меню", "в начало", "вернись в начало", "басты мазир", "мазирге кайт"),
        "Возвращаюсь в главное меню.",
        "Басты мәзірге ораламын.",
    ),
    (
        WallNavAction.NEXT_SECTION,
        ("следующий раздел", "следующий проект", "келеси болим", "келеси жоба"),
        "Открываю следующий раздел.",
        "Келесі бөлімді ашамын.",
    ),
    (
        WallNavAction.PREV_SECTION,
        ("предыдущий раздел", "предыдущий проект", "алдынгы болим"),
        "Открываю предыдущий раздел.",
        "Алдыңғы бөлімді ашамын.",
    ),
    (
        WallNavAction.NEXT_SLIDE,
        ("дальше", "следующий слайд", "вперед", "ари карай", "келеси слайд"),
        "Листаю дальше.",
        "Әрі қарай парақтаймын.",
    ),
    (
        WallNavAction.PREV_SLIDE,
        ("назад", "предыдущий слайд", "артка"),
        "Возвращаюсь на слайд назад.",
        "Алдыңғы слайдқа ораламын.",
    ),
)


class WallIntentMatcher:
    """Matches transcripts against the wall command matrix."""

    def __init__(self, config_path: str | None = None) -> None:
        self._sections = list(_DEFAULT_SECTIONS)
        if config_path and Path(config_path).exists():
            self._apply_overrides(
                yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
            )

    def _apply_overrides(self, raw: dict[str, Any]) -> None:
        """Customer YAML: per-section extra aliases and final speak texts."""
        overrides = raw.get("sections", {})
        updated: list[_SectionRule] = []
        for rule in self._sections:
            override = overrides.get(rule.section.value, {})
            aliases = rule.aliases
            for alias in override.get("aliases", []):
                words = tuple(_normalize(str(alias)))
                if words:
                    aliases = (*aliases, words)
            updated.append(
                _SectionRule(
                    section=rule.section,
                    aliases=aliases,
                    speak_ru=str(override.get("speak_ru", rule.speak_ru)),
                    speak_kz=str(override.get("speak_kz", rule.speak_kz)),
                )
            )
        self._sections = updated

    def match(self, text: str) -> WallIntentMatch | None:
        words = _normalize(text)
        if not words:
            return None
        language = detect_language(text)
        nav = self._match_nav(words, language)
        if nav is not None:
            return nav
        section = self._match_section(words, language)
        if section is not None:
            return section
        return self._match_category(words, language)

    def _match_nav(self, words: list[str], language: Language) -> WallIntentMatch | None:
        if len(words) > _MAX_NAV_WORDS:
            return None
        for action, aliases, speak_ru, speak_kz in _NAV_RULES:
            for alias in aliases:
                alias_words = alias.split()
                if all(_word_in(w, words) for w in alias_words):
                    return WallIntentMatch(
                        command=WallCommand(kind=WallCommandKind.NAVIGATE, nav=action),
                        speak=speak_kz if language is Language.KK else speak_ru,
                        language=language,
                    )
        return None

    def section_of(self, text: str) -> WallSection | None:
        """Which project a phrase talks about, ignoring the "show" verb rule.

        Used by the presenter KB for factual questions («кто строит аэропорт
        Зайсан?») where the section is context, not a command.
        """
        words = _normalize(text)
        for rule in self._sections:
            for alias in rule.aliases:
                if all(_word_in(w, words) for w in alias):
                    return rule.section
        return None

    def _match_section(self, words: list[str], language: Language) -> WallIntentMatch | None:
        has_verb = any(_word_in(verb, words) for verb in _SHOW_VERBS)
        for rule in self._sections:
            for alias in rule.aliases:
                if len(alias) == 1 and not has_verb:
                    continue  # bare place name needs an explicit "show" verb
                if all(_word_in(w, words) for w in alias):
                    return WallIntentMatch(
                        command=WallCommand(
                            kind=WallCommandKind.OPEN_SECTION, section=rule.section
                        ),
                        speak=rule.speak_kz if language is Language.KK else rule.speak_ru,
                        language=language,
                    )
        return None

    def _match_category(self, words: list[str], language: Language) -> WallIntentMatch | None:
        has_verb = any(_word_in(verb, words) for verb in _SHOW_VERBS)
        if not has_verb:
            return None
        for section, aliases, speak_ru, speak_kz in _CATEGORY_ALIASES:
            if any(_word_in(alias, words) for alias in aliases):
                return WallIntentMatch(
                    command=WallCommand(kind=WallCommandKind.OPEN_SECTION, section=section),
                    speak=speak_kz if language is Language.KK else speak_ru,
                    language=language,
                )
        return None
