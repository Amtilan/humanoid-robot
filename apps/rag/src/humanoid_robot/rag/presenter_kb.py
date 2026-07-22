"""Presenter knowledge base — the 12 transport projects the robot may discuss.

Loaded from a YAML generated out of the wall application's own data files
(``deploy/scripts/gen-presenter-kb.py``), so the robot voices exactly the
facts the wall shows. Two consumption paths, mirroring ``GuardKb``:

* ``lookup(text)`` — deterministic RU/KZ answers for factual questions
  («сколько километров», «кто подрядчик», «когда завершат», «какой статус»)
  about a recognised project — exact data, not an LLM guess;
* ``reference_block()`` — the whole KB rendered into the presenter system
  prompt, so free-form LLM answers use ONLY approved facts;
* ``PRESENTER_SYSTEM_PROMPT_RU`` — the plan §6 dialogue scenario: allowed
  topics, tone, and the exact refusal phrases for everything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from humanoid_robot.domain.voice import Language
from humanoid_robot.domain.wall import WallSection
from humanoid_robot.observability import get_logger
from humanoid_robot.rag.wall_intent import WallIntentMatcher, detect_language

_LOG = get_logger("cortex-rag.presenter_kb")

PRESENTER_SYSTEM_PROMPT_RU = (
    "Ты — робот-презентатор Министерства транспорта Республики Казахстан. "
    "Ты стоишь у видеостены и рассказываешь посетителям о 12 инфраструктурных "
    "проектах: автодороги, железные дороги и аэропорты.\n"
    "Правила:\n"
    "- Отвечай кратко (одно-три предложения), вежливо и официально.\n"
    "- О проектах говори ТОЛЬКО по справке ниже; не выдумывай цифры и факты.\n"
    "- Если спрашивают, кто ты, что ты умеешь, чем можешь помочь или "
    "здороваются — ОБЯЗАТЕЛЬНО дружелюбно представься: ты робот-презентатор "
    "Министерства транспорта, показываешь на видеостене проекты автодорог, "
    "железных дорог и аэропортов и отвечаешь на вопросы о них. Предложи "
    "выбрать, что показать.\n"
    "- Разрешены: проекты из справки, помощь с презентацией на видеостене, "
    "рассказ о себе и своих возможностях, вежливые приветствия и прощания.\n"
    "- Только на вопросы ВНЕ этих тем (политика, мнения, другие ведомства, "
    "личные темы, посторонние просьбы) отвечай ровно этой фразой: «Извините, "
    "я не уполномочен отвечать на этот вопрос. Пожалуйста, обратитесь к "
    "сотруднику.»\n"
    "- Если к тебе обратились на казахском — отвечай на казахском; фраза "
    "отказа на казахском: «Кешіріңіз, бұл сұраққа жауап беруге өкілеттігім "
    "жоқ. Қызметкерге жүгінуіңізді сұраймын.»"
)

_ATTRS = ("length", "contractor", "deadline", "status")

# Attribute keywords on the normalized (Kazakh-folded, lowercased) text.
_ATTR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("length", re.compile(r"протяжен|километр|длин|узынды|канша\s*км")),
    # «строител(?!ьств)»: слово «строительство» в вопросах о сроках не должно
    # опознаваться как вопрос о подрядчике.
    (
        "contractor",
        re.compile(r"подрядчик|кто\s+строит|строител(?!ьств)|мердигер|курылысшы|ким\s+салып"),
    ),
    (
        "deadline",
        re.compile(
            r"срок|когда\s+(построй|завер|сдад|заканч|откро)|заверш|сдач|мерзим|аяктал|качан"
        ),
    ),
    ("status", re.compile(r"статус|готовност|стади|исполнени|процент|мартебе|орындал")),
)

_ANSWER_TEMPLATES_RU = {
    "length": "Протяжённость проекта «{name}» — {value}.",
    "contractor": "Подрядчик проекта «{name}» — {value}.",
    "deadline": "Срок завершения проекта «{name}» — {value}.",
    "status": "Статус исполнения проекта «{name}» — {value}.",
}
_ANSWER_TEMPLATES_KZ = {
    "length": "«{name}» жобасының ұзындығы — {value}.",
    "contractor": "«{name}» жобасының мердігері — {value}.",
    "deadline": "«{name}» жобасының аяқталу мерзімі — {value}.",
    "status": "«{name}» жобасының орындалу мәртебесі — {value}.",
}
_ATTR_LABELS_RU = {
    "length": "протяжённость",
    "contractor": "подрядчик",
    "deadline": "срок завершения",
    "status": "статус",
}


@dataclass(slots=True)
class PresenterKb:
    """Parsed project reference data (RU/KZ) keyed by wall section."""

    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    matcher: WallIntentMatcher = field(default_factory=WallIntentMatcher)

    @classmethod
    def load(cls, path: str | Path, matcher: WallIntentMatcher | None = None) -> PresenterKb:
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            _LOG.info("presenter_kb.absent", path=str(path))
            return cls(matcher=matcher or WallIntentMatcher())
        except Exception:
            _LOG.exception("presenter_kb.unreadable", path=str(path))
            return cls(matcher=matcher or WallIntentMatcher())
        sections = {
            str(key): {str(k): str(v) for k, v in item.items()}
            for key, item in (raw.get("sections") or {}).items()
            if isinstance(item, dict)
        }
        _LOG.info("presenter_kb.loaded", sections=len(sections))
        return cls(sections=sections, matcher=matcher or WallIntentMatcher())

    @property
    def empty(self) -> bool:
        return not self.sections

    def _section_data(self, section: WallSection) -> dict[str, str] | None:
        return self.sections.get(section.value)

    def lookup(self, text: str) -> str | None:
        """Deterministic factual answer, or None to let the LLM handle it."""
        if self.empty:
            return None
        normalized = " ".join(_normalize_words(text))
        attr = None
        for name, rx in _ATTR_PATTERNS:
            if rx.search(normalized):
                attr = name
                break
        if attr is None:
            return None
        section = self.matcher.section_of(text)
        if section is None:
            return None
        data = self._section_data(section)
        if data is None:
            return None
        language = detect_language(text)
        suffix = "kz" if language is Language.KK else "ru"
        value = data.get(f"{attr}_{suffix}") or data.get(f"{attr}_ru")
        if not value:
            return None
        name = data.get(f"name_{suffix}") or data.get("name_ru", section.value)
        template = (
            _ANSWER_TEMPLATES_KZ[attr] if language is Language.KK else _ANSWER_TEMPLATES_RU[attr]
        )
        return template.format(name=name, value=value)

    def reference_block(self) -> str:
        """The whole KB as a справка block for the presenter system prompt."""
        if self.empty:
            return ""
        lines = ["", "СПРАВКА ПО ПРОЕКТАМ (единственный источник фактов):"]
        for data in self.sections.values():
            name = data.get("name_ru", "?")
            kind = data.get("kind", "проект")
            facts = [
                f"{_ATTR_LABELS_RU[attr]} — {data[f'{attr}_ru']}"
                for attr in _ATTRS
                if data.get(f"{attr}_ru")
            ]
            extra = data.get("extra_ru", "").strip()
            tail = f" {extra}" if extra else ""
            lines.append(f"- {name} ({kind}): {'; '.join(facts)}.{tail}")
        lines.append(
            "Если нужного факта нет в справке — скажи, что уточнит сотрудник, "
            "и предложи показать проект на экране."
        )
        return "\n".join(lines)


def _normalize_words(text: str) -> list[str]:
    from humanoid_robot.rag.wall_intent import _normalize  # shared normalizer

    return _normalize(text)
