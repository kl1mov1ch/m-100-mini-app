import io
from datetime import datetime

import openpyxl
import pytest

from backend import bitrix
from backend.workbook_calculation import cache_formulas, verify_calculations


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
