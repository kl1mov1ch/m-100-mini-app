import io
from datetime import datetime

import openpyxl
import pytest

from backend import bitrix
from backend.workbook_calculation import cache_formulas, verify_calculations
from backend.workbook_journal import format_journal, verify_day_totals


def test_all_dependent_columns_have_updated_values_without_opening_excel():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Монтаж"
    for column, value in enumerate(
        [
            "№",
            "Наименование",
            "Ед изм",
            "К-во",
            "ЗП за ед.",
            "ЗП за весь объём",
            "Остаток объёма",
            "Выполнено в деньгах на руки",
            "Выполненный объём",
        ],
        1,
    ):
        sheet.cell(1, column, value)
    sheet["J3"] = datetime(2026, 8, 19)
    for column, value in enumerate(
        [1, "Кабель", "м", 100, 2.35, "=E5*D5", None, "=I5*E5", "=SUM(J5:CZ5)", 2], 1
    ):
        sheet.cell(5, column, value)
    output = io.BytesIO()
    workbook.save(output)
    catalogue = bitrix.read_workbook(output.getvalue())["positions"]
    result = bitrix.patch_workbook(
        output.getvalue(), "2026-11-10", [{"item_id": "excel-5", "quantity": 10}], catalogue
    )
    formulas = openpyxl.load_workbook(io.BytesIO(result), data_only=False)["Монтаж"]
    values = openpyxl.load_workbook(io.BytesIO(result), data_only=True)["Монтаж"]
    assert formulas["I5"].value == "=SUM(J5:CZ5)"
    assert values["I5"].value == 12 and values["G5"].value == 88
    assert values["F5"].value == 235 and round(values["H5"].value, 2) == 28.2
    changed = bitrix.patch_workbook(
        result, "2026-11-10", [{"item_id": "excel-5", "quantity": 5}], catalogue
    )
    values = openpyxl.load_workbook(io.BytesIO(changed), data_only=True)["Монтаж"]
    assert values["I5"].value == 7 and values["G5"].value == 93
    verify_calculations(changed, changed)


def test_unsupported_formula_requires_clear_cell_confirmation():
    workbook = openpyxl.Workbook()
    workbook.active["B2"] = "=UNKNOWN(A1)"
    output = io.BytesIO()
    workbook.save(output)
    with pytest.raises(ValueError, match="B2"):
        cache_formulas(output.getvalue())


def test_guarded_source_formula_and_daily_payroll_on_new_sheet():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Инженерные сети"
    sheet["D5"] = 4
    sheet["E5"] = 145
    formula = '=IF(OR(D5="",E5=""),"",D5*E5)'
    sheet["F5"] = formula
    sheet["D6"] = 0
    sheet["E6"] = 145
    sheet["F6"] = '=IF(OR(D6="",E6=""),"",D6*E6)'
    sheet["F7"] = '=IF(OR(D7="",E7=""),"",D7*E7)'
    sheet["L9"] = "=UNKNOWN(A1)"
    stream = io.BytesIO()
    workbook.save(stream)
    positions = [{"id": "one", "name": "Блок", "unit": "шт", "planned": 4, "rate": 145}]
    day = "2026-11-11"
    entries = [{"item_id": "one", "date": day, "quantity": 1}]
    issues = []
    content = format_journal(stream.getvalue(), positions, entries, {day: 3}, issues)
    cached = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    assert cached["Инженерные сети"]["F5"].value == 580
    assert cached["Инженерные сети"]["F6"].value == 0
    assert cached["Инженерные сети"]["F7"].value is None
    assert {issue["cell"] for issue in issues} == {"L9"}
    original = openpyxl.load_workbook(io.BytesIO(content))["Инженерные сети"]
    assert original["F5"].value == formula and original["L9"].value == "=UNKNOWN(A1)"
    verify_day_totals(
        content,
        day,
        {
            "amount": 145,
            "crew_count": 3,
            "per_person": 48.33,
            "extra_people": 1,
            "extra_per_person": 48.34,
        },
        1,
    )
    older_day = "2026-11-10"
    updated = format_journal(content, positions, entries, {day: 3, older_day: 1}, [])
    journal = openpyxl.load_workbook(io.BytesIO(updated), data_only=True)["Журнал работ"]
    assert str(journal["J3"].value)[:10] == day and str(journal["K3"].value)[:10] == older_day
