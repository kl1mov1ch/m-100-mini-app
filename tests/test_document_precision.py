import asyncio
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from backend.documents import extraction, worker
from backend.documents.normalization import build_groups, financial_summary, normalise
from backend.naming import unique_project_name


def item(
    page=1, quantity=10, unit="м", quote="П1: труба 10 м", name="Монтаж трубы Ø6 мм", notes=""
):
    return dict(
        page=page,
        quantity=quantity,
        unit=unit,
        quote=quote,
        name=name,
        category="Вентиляция",
        notes=notes,
        confirmed=False,
    )


@pytest.mark.parametrize(
    "unit,quantity,expected",
    [
        ("м.п.", 10, "10"),
        ("см", 150, "1.50"),
        ("мм", 2500, "2.500"),
        ("км", "0.1", "100.0"),
        ("см²", 10000, "1.0000"),
        ("л", 1000, "1.000"),
        ("т", "1.5", "1500.0"),
    ],
)
def test_unit_conversion_is_dimensionally_correct(unit, quantity, expected):
    assert Decimal(normalise(item(unit=unit, quantity=quantity))["quantity"]) == Decimal(expected)


def test_dimension_and_diameter_and_conditions_remain_separate():
    groups = build_groups(
        [
            item(unit="м"),
            item(unit="м²"),
            item(name="Монтаж трубы Ø10 мм"),
            item(notes="На высоте 12 м"),
        ]
    )
    assert len(groups) == 4


def test_disjoint_systems_sum_but_overlapping_sources_require_resolution():
    rows = [item(1, 10, quote="П1: труба 10 м"), item(2, 15, quote="П2: труба 15 м")]
    group = build_groups(rows)[0]
    assert Decimal(group["quantity"]) == 25 and not group["issues"]
    duplicated = build_groups([item(1), item(2, quote="П1 спецификация: труба 10 м")])[0]
    assert duplicated["quantity"] is None and duplicated["issues"]
    assert Decimal(duplicated["proposed_quantity"]) == 20
    assert financial_summary([duplicated])["amount"] == 0


def test_overlapping_chunk_results_are_not_double_counted():
    group = build_groups([item(), item()])[0]
    assert group["quantity"] == "10" and len(group["sources"]) == 1


def test_unknown_volume_never_becomes_zero_and_unconfirmed_money_is_excluded():
    group = build_groups([item(quantity=None)])[0]
    assert group["quantity"] is None
    known = build_groups([item(quantity="0.335")])[0]
    known.update(rate="1", confirmed=False)
    assert financial_summary([known])["amount"] == 0
    known["confirmed"] = True
    assert financial_summary([known])["amount"] == 0.34


def test_object_names_are_unique_ignoring_case_and_spaces():
    assert (
        unique_project_name("  Детский   сад ", ["детский сад", "Детский сад (2)"])
        == "Детский сад (3)"
    )


@pytest.mark.parametrize(
    "quote,quantity,unit",
    [
        ("Диаметр 6 мм", 6, "мм"),
        ("Расход 100 м³/ч", 100, "м³"),
        ("Мощность 15 кВт", 15, "м"),
        ("Труба 12 м", 99, "м"),
    ],
)
def test_equipment_parameters_do_not_become_work_quantities(monkeypatch, quote, quantity, unit):
    async def complete(*args):
        return {
            "works": [
                {
                    "name": "Труба",
                    "category": "Вентиляция",
                    "quote": quote,
                    "quantity": quantity,
                    "unit": unit,
                }
            ]
        }

    monkeypatch.setattr(extraction.matcher, "complete", complete)
    works, _ = asyncio.run(extraction.propose(quote, 1, {}, "Вентиляция"))
    assert len(works) == 1 and works[0]["quantity"] is None


def test_ocr_quotes_preserve_all_rows_and_source_bounds(monkeypatch):
    from backend.documents import table_ocr

    monkeypatch.setattr(table_ocr, "recognize", lambda *args: None)
    text = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    text += "1\t1\t0\t0\t0\t0\t0\t0\t1000\t1000\t-1\t\n"
    text += '5\t1\t1\t1\t1\t1\t20\t30\t80\t20\t90\t"Труба\n'
    text += "5\t1\t1\t1\t2\t1\t20\t60\t80\t20\t91\t12 м\n"
    monkeypatch.setattr(worker.shutil, "which", lambda *args: "tool")
    calls = iter([subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, text)])
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs: next(calls))
    result = worker.ocr_page(Path("source.pdf"), 1, Path("data"))
    assert result["text"] == '"Труба\n12 м'
    assert result["layout"]["width"] == 1000
    assert len(result["layout"]["lines"]) == 2
    assert result["layout"]["lines"][1]["top"] == 60


def test_same_page_overlapping_work_is_not_silently_summed():
    result = build_groups([item(quote="Труба: 10 м"), item(quote="Та же труба, всего 10 м")])[0]
    assert result["quantity"] is None and result["issues"]


def test_table_quantity_requires_independent_check_and_stays_flagged(monkeypatch):
    text = "Наименование | Длина, м | Труба стальная | 12"
    replies = iter(
        [
            {
                "works": [
                    {
                        "name": "Монтаж трубы стальной",
                        "category": "Отопление",
                        "unit": "м",
                        "quantity": 12,
                        "quantity_header": "Длина, м",
                        "quantity_cell": "12",
                        "unit_evidence": "м",
                        "quote": "Труба стальная | 12",
                    }
                ]
            },
            {"accepted": [0]},
        ]
    )

    async def complete(*args):
        return next(replies)

    monkeypatch.setattr(extraction.matcher, "complete", complete)
    works, _ = asyncio.run(extraction.propose(text, 1, {}, "Отопление"))
    assert works[0]["quantity"] == 12
    assert build_groups(works)[0]["issues"]


def test_structured_table_recovers_quote_and_column_without_ai_transcription(monkeypatch):
    text = "Таблица: ячейки по строкам и колонкам.\nСтрока 2: C3–C4=Поверхность, м² |\nСтрока 3: C3–C4=11 |\nСтрока 4: C3–C4=12,75 | C1–C2=Воздуховод 200х300 |"
    replies = iter([{"works": [{"name": "Изоляция воздуховода 200х300", "category": "Вентиляция", "unit": "м²", "quantity": 12.75, "source_row": 4, "quantity_column": "C3–C4"}]}, {"accepted": [0]}])
    async def complete(*args):
        return next(replies)
    monkeypatch.setattr(extraction.matcher, "complete", complete)
    works, _ = asyncio.run(extraction.propose(text, 1, {}, "Вентиляция"))
    assert len(works) == 1 and works[0]["quantity"] == 12.75
    assert works[0]["quote"] in text and "200х300" in works[0]["quote"]
