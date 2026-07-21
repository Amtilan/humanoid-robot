#!/usr/bin/env python3
"""Generate presenter-kb.yaml from the MinTrans wall application's own data.

The wall app (Factories.exe) keeps each section's info panels as text files:

    Datas/<Section>/BlockInfoView/0.txt   протяжённость
    Datas/<Section>/BlockInfoView/1.txt   подрядчик
    Datas/<Section>/BlockInfoView/2.txt   срок завершения
    Datas/<Section>/BlockInfoView/3.txt   статус исполнения

Each file holds the Russian value, the Kazakh value, then the RU/KZ labels
(multiline values are separated by blank lines and use a literal "\\n"
line-break marker). This script parses those panels into the robot's
presenter knowledge base, so the facts the robot voices are — by
construction — the same facts the wall shows.

Usage:
    python3 deploy/scripts/gen-presenter-kb.py /path/to/MinTrans/PC \
        > deploy/config/presenter-kb.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

PANELS = {0: "length", 1: "contractor", 2: "deadline", 3: "status"}

# Canonical names per the app's developer documentation (Datas_Документация.txt
# + Datas_құжаттама.txt). Avto5 is present in the app data but missing from its
# docs — the name is the contractor's working title, to be confirmed (plan §3).
NAMES: dict[str, tuple[str, str, str]] = {
    "Avto1": (
        "автодорога",
        "Кызылорда — Жезказган, км 216–424",
        "Қызылорда — Жезқазған, 216–424 км",
    ),
    "Avto2": (
        "автодорога",
        "Актобе — Карабутак — Улгайсын, км 791–819",
        "Ақтөбе — Қарабұтақ — Ұлғайсын, 791–819 км",
    ),
    "Avto3": ("автодорога", "мост через реку Иртыш", "Ертіс өзені арқылы көпір"),
    "Avto4": ("автодорога", "обход города Сарыагаш", "Сарыағаш қаласын айналып өту"),
    "Avto5": (
        "автодорога",
        "Актобе — Улгайсын (название уточняется)",
        "Ақтөбе — Ұлғайсын (атауы нақтылануда)",
    ),
    "JD1": ("железная дорога", "Дарбаза — Мактаарал", "Дарбаза — Мақтаарал"),
    "JD2": ("железная дорога", "Мойынты — Кызылжар", "Мойынты — Қызылжар"),
    "JD3": ("железная дорога", "Бахты — Аягоз", "Бақты — Аягөз"),
    "Aero1": ("аэропорт", "аэропорт Зайсан, строительство", "Зайсан әуежайының құрылысы"),
    "Aero2": (
        "аэропорт",
        "аэропорт Катон-Карагай, строительство",
        "Катонқарағай әуежайының құрылысы",
    ),
    "Aero3": ("аэропорт", "аэропорт Кендерли, строительство", "Кендірлі әуежайының құрылысы"),
    "Aero4": (
        "аэропорт",
        "аэропорт Аркалык, возобновление деятельности",
        "Арқалық әуежайының қызметін қалпына келтіру",
    ),
}


def parse_panel(path: Path) -> tuple[str, str]:
    """Return (value_ru, value_kz) from one BlockInfoView panel file."""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    # Drop the two trailing labels (RU + KZ), keeping positions of blanks.
    non_blank = [i for i, ln in enumerate(lines) if ln]
    if len(non_blank) < 4:  # value_ru, value_kz, label_ru, label_kz
        return "", ""
    label_start = non_blank[-2]
    body = lines[:label_start]
    # Trim trailing blanks of the body.
    while body and not body[-1]:
        body.pop()
    # Multiline values: RU block / blank line / KZ block. Single-line values:
    # exactly two lines, RU then KZ.
    blocks: list[list[str]] = [[]]
    for ln in body:
        if ln:
            blocks[-1].append(ln)
        elif blocks[-1]:
            blocks.append([])
    if blocks and not blocks[-1]:
        blocks.pop()

    def join(block: list[str]) -> str:
        return " ".join(part.replace("\\n", " ").strip() for part in block).strip()

    if len(blocks) == 2:
        return join(blocks[0]), join(blocks[1])
    flat = [ln for ln in body if ln]
    half = len(flat) // 2
    return join(flat[:half]), join(flat[half:])


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    datas = Path(sys.argv[1]) / "Datas"
    out: list[str] = [
        "# Справочные данные робота-презентатора — СГЕНЕРИРОВАНО из данных",
        "# приложения видеостены (Datas/*/BlockInfoView). Не редактировать",
        "# вручную то, что приходит из приложения — перегенерировать:",
        "#   python3 deploy/scripts/gen-presenter-kb.py <MinTrans/PC> > deploy/config/presenter-kb.yaml",
        "# Дополнительные материалы заказчика — в extra_ru/extra_kz.",
        "",
        "sections:",
    ]
    for section, (kind, name_ru, name_kz) in NAMES.items():
        panel_dir = datas / section / "BlockInfoView"
        out.append(f"  {section}:")
        out.append(f'    kind: "{kind}"')
        out.append(f'    name_ru: "{name_ru}"')
        out.append(f'    name_kz: "{name_kz}"')
        for index, attr in PANELS.items():
            panel = panel_dir / f"{index}.txt"
            if not panel.exists():
                continue
            value_ru, value_kz = parse_panel(panel)
            # Data-quality flag from plan §3: every airport section carries the
            # same template "152 км" — clearly unfilled, so don't voice it.
            if attr == "length" and section.startswith("Aero"):
                out.append(
                    f'    # {attr}: "{value_ru}"  # шаблонное значение в данных приложения — не озвучиваем (уточняется Заказчиком)'
                )
                continue
            out.append(f'    {attr}_ru: "{value_ru}"')
            out.append(f'    {attr}_kz: "{value_kz}"')
    print("\n".join(out))


if __name__ == "__main__":
    main()
