import io
from datetime import date

import openpyxl
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import quote_sheetname

from .expense_rules import extra_position
from .workbook_journal import AMOUNT_FORMAT, is_journal, journal_row

MARKER = "M100 • Доп. расходы"
SUMMARY_MARKER = "M100 • Итог затрат"


def is_expense_sheet(sheet):
    return sheet["A1"].value == MARKER


def write_summary(book):
    expenses = next((sheet for sheet in book if is_expense_sheet(sheet)), None)
    journals = [sheet for sheet in book if is_journal(sheet)]
    if not expenses or not journals:
        return
    main = journals[0]
    header = next((cell.row for cell in main["A"] if cell.value == SUMMARY_MARKER), None)
    start = header if header else main.max_row + 2
    work_refs = []
    for sheet in journals:
        for cell in sheet["A"]:
            details = journal_row(cell)
            if details and extra_position(
                {"section": details[1], "name": sheet.cell(cell.row, 2).value}
            ):
                sheet.row_dimensions[cell.row].hidden = True
        total_row = next(cell.row for cell in sheet["B"] if cell.value == "Сумма работ, BYN")
        work_refs.append(f"{quote_sheetname(sheet.title)}!H{total_row}")
    main.cell(start, 1, SUMMARY_MARKER)
    main.row_dimensions[start].hidden = True
    for offset, (label, formula) in enumerate(
        (
            ("Работы по объекту", f"=ROUND(SUM({','.join(work_refs)}),2)"),
            ("Доп. расходы", f"={quote_sheetname(expenses.title)}!F2"),
            ("Итого затраты по объекту", f"=ROUND(SUM(H{start + 1}:H{start + 2}),2)"),
        ),
        1,
    ):
        main.cell(start + offset, 2, label).font = Font(bold=offset == 3)
        main.cell(start + offset, 8, formula).number_format = AMOUNT_FORMAT


def with_expenses(content, rows):
    from .workbook_calculation import cache_formulas

    book = openpyxl.load_workbook(io.BytesIO(content))
    previous = next((sheet for sheet in book if is_expense_sheet(sheet)), None)
    title = previous.title if previous else "Доп. расходы"
    if previous:
        book.remove(previous)
    if title in book:
        title = "Доп. расходы М100"
    sheet = book.create_sheet(title)
    sheet["A1"] = MARKER
    sheet.row_dimensions[1].hidden = True
    sheet["B2"] = "Итого доп. расходы"
    sheet["F2"] = f"=ROUND(SUM(F4:F{max(4, len(rows) + 3)}),2)"
    sheet["F2"].number_format = AMOUNT_FORMAT
    sheet.append(
        ["Дата", "Работа или расход", "Ед.", "Количество", "Цена за ед.", "Сумма", "Примечание"]
    )
    for item in rows:
        index = sheet.max_row + 1
        sheet.append(
            [
                date.fromisoformat(item["date"]),
                item["name"],
                item["unit"],
                float(item["quantity"]),
                float(item["rate"]),
                f"=ROUND(ROUND(D{index}*E{index},8),2)",
                item["note"],
            ]
        )
        for col in (2, 3, 7):
            sheet.cell(index, col).data_type = "s"
        sheet.cell(index, 1).number_format = "dd.mm.yyyy"
        for col in (5, 6):
            sheet.cell(index, col).number_format = AMOUNT_FORMAT
    line = Side(style="thin", color="D2DDE8")
    for row in sheet.iter_rows(min_row=3):
        for cell in row:
            cell.border = Border(right=line, bottom=line)
            if cell.row == 3:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="21344A")
    for column, width in zip("ABCDEFG", (14, 44, 12, 14, 16, 16, 40), strict=True):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:G{sheet.max_row}"
    write_summary(book)
    output = io.BytesIO()
    book.save(output)
    return cache_formulas(output.getvalue(), [], original=content)
