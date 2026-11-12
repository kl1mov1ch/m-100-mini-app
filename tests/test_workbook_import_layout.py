import asyncio
import io
from datetime import date

import openpyxl
import pytest

from backend import bitrix, tables, workbook_revision
from backend.workbook_journal import format_journal


def workbook_bytes(book):
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_stacked_payroll_headers_and_multiple_working_sheets():
    book = openpyxl.Workbook()
    original = book.active
    original.title = "Вентиляция"
    original.append(["№", "Наименование", "Ед. изм.", "К-во", "Работа", "Контракт"])
    original.append([None, None, None, None, "ЗП на руки\nза ед.", "Цена работ за ед."])
    original.append([None, None, None, None, None, None, date(2026, 11, 11)])
    original.append([1, "Установка", "шт", 6, 400, 1480, 2])
    original.append(["№", "Наименование", "Ед. изм.", "К-во", "Расценка"])
    original.append([1, "Трубопровод", "м", 10, 30])
    second = book.create_sheet("Электрика")
    second.append(["Наименование", "Ед. изм.", "План", "Расценка"])
    second.append(["Кабель", "м", 15, 20])
    source = workbook_bytes(book)

    mappings, warnings = tables.discover(source)
    assert not warnings
    parsed = tables.extract(source, mappings)
    assert [(p["name"], p["rate"]) for p in parsed["positions"]] == [
        ("Установка", 400),
        ("Трубопровод", 30),
        ("Кабель", 20),
    ]
    assert [entry["quantity"] for entry in parsed["entries"]] == [2]
    issues = []
    working = format_journal(source, parsed["positions"], parsed["entries"], {}, issues, mappings)
    assert not issues
    assert workbook_revision.changes(source, working, original_only=True) is None
    result = bitrix.read_workbook(working)
    assert len(result["sheets"]) == 3
    assert {p["id"] for p in result["positions"]} == {p["id"] for p in parsed["positions"]}
    assert result["entries"] == parsed["entries"]
    actual = openpyxl.load_workbook(io.BytesIO(working))
    assert all(actual[item["name"]].freeze_panes == "J5" for item in result["sheets"])


def test_ai_cannot_reuse_a_column_already_claimed_by_the_estimate(monkeypatch):
    book = openpyxl.Workbook()
    book.active.append(["Наименование", "Ед. изм.", "План", "Оплата"])
    book.active.append(["Кабель", "м", 15, 20])
    source = workbook_bytes(book)
    monkeypatch.setattr(tables.matcher, "provider", lambda settings: {"key": "test"})

    async def complete(prompt, sample, settings):
        if "сметы" in prompt:
            return {"sheets": [{"name": book.active.title, "mapping": {"rate": 3}}]}
        return {}

    monkeypatch.setattr(tables.matcher, "complete", complete)
    data = asyncio.run(tables.analyze(source))
    assert data["sheets"][0]["mapping"]["planned"] == 3
    assert data["sheets"][0]["mapping"]["rate"] is None
    data["sheets"][0]["mapping"]["rate"] = 3
    with pytest.raises(ValueError, match="столбец C"):
        tables.extract(source, data["sheets"])
