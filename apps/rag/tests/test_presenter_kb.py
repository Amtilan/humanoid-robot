"""PresenterKb — deterministic project facts and prompt reference block."""

from __future__ import annotations

from pathlib import Path

import pytest

from humanoid_robot.rag.presenter_kb import PresenterKb

_KB_YAML = """
sections:
  Avto1:
    kind: "автодорога"
    name_ru: "Кызылорда — Жезказган, км 216–424"
    name_kz: "Қызылорда — Жезқазған, 216–424 км"
    length_ru: "208 км"
    length_kz: "208 км"
    contractor_ru: "China Harbour Engineering Company"
    contractor_kz: "China Harbour Engineering Company"
    deadline_ru: "2027"
    deadline_kz: "2027"
    status_ru: "СМР"
    status_kz: "СМР"
  Aero1:
    kind: "аэропорт"
    name_ru: "аэропорт Зайсан, строительство"
    name_kz: "Зайсан әуежайының құрылысы"
    contractor_ru: "ТОО «Элхон»"
    contractor_kz: "«Элхон» ЖШС"
    deadline_ru: "июнь 2026"
    deadline_kz: "маусым 2026"
    status_ru: "43%"
    status_kz: "43%"
"""


@pytest.fixture(scope="module")
def kb(tmp_path_factory: pytest.TempPathFactory) -> PresenterKb:
    path = tmp_path_factory.mktemp("kb") / "presenter-kb.yaml"
    path.write_text(_KB_YAML, encoding="utf-8")
    return PresenterKb.load(path)


def test_length_question_ru(kb: PresenterKb) -> None:
    answer = kb.lookup("какая протяжённость дороги Кызылорда Жезказган?")
    assert answer is not None
    assert "208 км" in answer
    assert "Кызылорда" in answer


def test_contractor_question_ru(kb: PresenterKb) -> None:
    answer = kb.lookup("кто подрядчик аэропорта Зайсан")
    assert answer is not None
    assert "Элхон" in answer


def test_deadline_question_kz(kb: PresenterKb) -> None:
    answer = kb.lookup("Зайсан әуежайы қашан аяқталады, мерзімі қандай?")
    assert answer is not None
    assert "маусым 2026" in answer  # Kazakh value for a Kazakh question
    assert "әуежай" in answer


def test_status_question(kb: PresenterKb) -> None:
    answer = kb.lookup("какой статус исполнения по аэропорту Зайсан")
    assert answer is not None
    assert "43%" in answer


def test_missing_fact_returns_none(kb: PresenterKb) -> None:
    # Aero1 deliberately has no length (template data was unfilled).
    assert kb.lookup("сколько километров аэропорт Зайсан") is None


def test_no_section_or_no_attr_defers_to_llm(kb: PresenterKb) -> None:
    assert kb.lookup("кто подрядчик") is None  # no project named
    assert kb.lookup("расскажи про Кызылорду и Жезказган") is None  # no fact asked


def test_reference_block_lists_projects(kb: PresenterKb) -> None:
    block = kb.reference_block()
    assert "СПРАВКА" in block
    assert "208 км" in block
    assert "Элхон" in block


def test_absent_file_is_empty() -> None:
    kb = PresenterKb.load(Path("/nonexistent/presenter-kb.yaml"))
    assert kb.empty
    assert kb.lookup("кто подрядчик аэропорта Зайсан") is None
    assert kb.reference_block() == ""


def test_generated_repo_kb_parses() -> None:
    repo_kb = Path(__file__).parents[3] / "deploy" / "config" / "presenter-kb.yaml"
    kb = PresenterKb.load(repo_kb)
    assert len(kb.sections) == 12
    answer = kb.lookup("кто строит мост через Иртыш")
    assert answer is not None
    assert "Казахдорстрой" in answer
