import io
import json
from copy import copy
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import openpyxl
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.workbook.views import BookView

JOURNAL_MARKER = "M100 • Журнал работ"
JOURNAL_SOURCE = "M100 • рабочий лист"
AMOUNT_FORMAT = '#,##0.00 "BYN"'
VOLUME_FORMAT = "#,##0.####;[Red]-#,##0.####;0"
DEFAULT_FILLS = {"21344A", "E8F2FB", "F5F8FC", "FFFFFF"}


def is_journal(sheet):
    return sheet["A2"].value == JOURNAL_MARKER


def manual_fill(cell):
    fill = cell.fill
    return bool(getattr(fill, "fill_type", None)) and not (
        fill.fill_type == "solid"
        and fill.fgColor.type == "rgb"
        and fill.fgColor.rgb[-6:] in DEFAULT_FILLS
    )


def saved_fills(sheet):
    result = {}
    for row in sheet.iter_rows(min_row=5):
        metadata = journal_row(row[0])
        ident = metadata[0] if metadata else row[0].row
        if not isinstance(row[0].value, int):
            continue
        for cell in row:
            if manual_fill(cell):
                day = sheet.cell(3, cell.column).value if cell.column >= 10 else None
                key = day.isoformat()[:10] if isinstance(day, date) else cell.column
                result[ident, key] = copy(cell.fill)
    return result


def journal_mapping(sheet):
    if not is_journal(sheet) or sheet["B2"].value != JOURNAL_SOURCE:
        return None
    return {
        "name": sheet.title,
        "header_row": 1,
        "date_row": 3,
        "mapping": {"name": 2, "unit": 3, "planned": 4, "rate": 5, "completed": 9},
        "rows": sum(1 for cell in sheet["A"] if isinstance(cell.value, int)),
        "columns": [
            {"index": cell.column, "label": str(cell.value)} for cell in sheet[1] if cell.value
        ],
    }


def journal_row(cell):
    if cell.comment and cell.comment.author == "M100":
        try:
            ident, section, baseline = json.loads(cell.comment.text)
            if (
                isinstance(ident, str)
                and isinstance(section, str)
                and isinstance(baseline, (float, int))
            ):
                return ident, section, baseline
        except (ValueError, TypeError):
            pass
    return None


def journal_sheet(book, existing, group, multiple):
    if existing:
        title = existing.title
        index = book.index(existing)
        book.remove(existing)
        return book.create_sheet(title, index)
    title = f"Работы · {group}"[:31] if multiple else "Журнал работ"
    if title in book:
        title = title[:24] + " · М100"
    return book.create_sheet(title)


def format_journal(content, catalogue, entries, crew_by_day, issues, mappings=None):
    from .workbook_calculation import cache_formulas

    book = openpyxl.load_workbook(io.BytesIO(content))
    journals = [sheet for sheet in book if is_journal(sheet)]
    source_by_title = {sheet.title: sheet["C2"].value or sheet.title for sheet in journals}
    source_ranges = {}
    for mapping in mappings or ():
        if mapping.get("group"):
            source_ranges.setdefault(mapping["name"], []).append(mapping)
    groups = {}
    for position in catalogue:
        source = position.get("source_sheet") or ""
        group = source_by_title.get(source)
        if group is None:
            group = next(
                (
                    mapping["group"]
                    for mapping in source_ranges.get(source, ())
                    if mapping["header_row"] < position["source_row"] <= mapping["end_row"]
                ),
                source,
            )
        groups.setdefault(group, []).append(position)
    if not groups:
        groups[""] = []
    previous = {sheet["C2"].value or sheet.title: sheet for sheet in journals}
    if len(journals) == len(groups) == 1 and not journals[0]["C2"].value:
        previous = {next(iter(groups)): journals[0]}
    for sheet in journals:
        if sheet not in [previous.get(group) for group in groups]:
            book.remove(sheet)
    if not book.views:
        book.views = [BookView()]
    if book.calculation is None:
        book.calculation = CalcProperties()
    book.calculation.fullCalcOnLoad = True
    days = {entry["date"] for entry in entries} | set(crew_by_day)
    quantities = {}
    for entry in entries:
        key = entry["item_id"], entry["date"]
        quantities[key] = quantities.get(key, 0) + entry["quantity"]
    for index, (group, positions) in enumerate(groups.items()):
        sheet = write_journal_sheet(
            book,
            previous.get(group),
            group,
            len(groups) > 1,
            positions,
            quantities,
            days,
            crew_by_day,
        )
        if index == 0:
            book.active = sheet
    output = io.BytesIO()
    book.save(output)
    return cache_formulas(output.getvalue(), issues, original=content)


def write_journal_sheet(
    book, previous, group, multiple, catalogue, quantities, work_days, crew_by_day
):
    fills = saved_fills(previous) if previous else {}
    previous_days = []
    if previous:
        previous_days = [
            value.isoformat()[:10]
            for cell in previous[3][9:]
            if isinstance((value := cell.value), date)
        ]
    sheet = journal_sheet(book, previous, group, multiple)
    days = previous_days + sorted(work_days - set(previous_days))
    sheet.append(
        [
            "№",
            "Наименование по спецификации",
            "Ед. изм.",
            "К-во по смете",
            "ЗП за ед., BYN",
            "По смете, BYN",
            "Остаток объёма",
            "Выполнено, BYN",
            "Выполненный объём",
        ]
    )
    sheet["A2"] = JOURNAL_MARKER
    sheet["B2"] = JOURNAL_SOURCE
    sheet["C2"] = group
    sheet["C2"].data_type = "s"
    sheet.row_dimensions[2].hidden = True
    sheet.row_dimensions[1].height = 36
    sheet.row_dimensions[3].height = 25
    last_column = get_column_letter(9 + len(days))
    last_row = 4 + len(catalogue)
    if days:
        sheet["J1"] = "Ежедневное выполнение"
        if len(days) > 1:
            sheet.merge_cells(f"J1:{last_column}1")
    for column, day in enumerate(days, 10):
        sheet.cell(3, column, date.fromisoformat(day)).number_format = "dd.mm.yyyy"
        sheet.cell(4, column, "Объём")
        sheet.column_dimensions[get_column_letter(column)].width = 17
    for row, position in enumerate(catalogue, 5):
        baseline = float(position.get("baseline") or 0)
        ordinal = sheet.cell(row, 1, row - 4)
        ordinal.comment = Comment(
            json.dumps([position["id"], position.get("section", ""), baseline], ensure_ascii=False),
            "M100",
        )
        name = sheet.cell(row, 2, str(position["name"]))
        name.data_type = "s"
        measure = sheet.cell(row, 3, str(position["unit"]))
        measure.data_type = "s"
        sheet.cell(row, 4, position["planned"])
        sheet.cell(row, 5, position["rate"])
        sheet.cell(row, 6, f"=ROUND(D{row}*E{row},2)")
        sheet.cell(row, 7, f"=D{row}-I{row}")
        sheet.cell(row, 8, f"=ROUND(I{row}*E{row},2)")
        sheet.cell(row, 9, f"={baseline}+SUM(J{row}:{last_column}{row})" if days else baseline)
        for column, day in enumerate(days, 10):
            sheet.cell(row, column, quantities.get((position["id"], day), 0))
        sheet.row_dimensions[row].height = max(20, min(70, 16 * (1 + len(position["name"]) // 55)))

    totals = last_row + 2
    labels = (
        "Сумма работ, BYN",
        "Работников",
        "На человека, BYN",
        "Чел. с +0,01 BYN",
        "С повышенной долей, BYN",
        "Позиций выполнено",
    )
    for row, label in enumerate(labels, totals):
        sheet.cell(row, 2, label)
        sheet.row_dimensions[row].height = 24
    if catalogue:
        sheet.cell(totals, 6, f"=SUM(F5:F{last_row})").number_format = AMOUNT_FORMAT
        sheet.cell(totals, 8, f"=SUM(H5:H{last_row})").number_format = AMOUNT_FORMAT
    for column, day in enumerate(days, 10):
        letter = get_column_letter(column)
        earned = f"{letter}{totals}"
        crew = f"{letter}{totals + 1}"
        share = f"{letter}{totals + 2}"
        extra = f"{letter}{totals + 3}"
        sheet.cell(
            totals + 5, column, f'=COUNTIF({letter}5:{letter}{last_row},">0")' if catalogue else 0
        )
        sheet.cell(
            totals,
            column,
            f"=ROUND(SUMPRODUCT({letter}5:{letter}{last_row},E5:E{last_row}),2)"
            if catalogue
            else 0,
        )
        if day in crew_by_day:
            sheet.cell(totals + 1, column, crew_by_day[day])
            sheet.cell(totals + 2, column, f"=INT(ROUND({earned}*100,0)/{crew})/100")
            sheet.cell(totals + 3, column, f"=MOD(ROUND({earned}*100,0),{crew})")
            sheet.cell(totals + 4, column, f'=IF({extra}=0,"",ROUND({share}+0.01,2))')
        for row in (totals, totals + 2, totals + 4):
            sheet.cell(row, column).number_format = AMOUNT_FORMAT

    line = Side(style="hair", color="D6E2F0")
    for row in sheet.iter_rows(min_row=1, max_row=totals + 5, max_col=9 + len(days)):
        for cell in row:
            header = cell.row == 1
            date_heading = cell.row in (3, 4) and cell.column >= 10
            total = cell.row >= totals
            color = (
                "21344A"
                if header
                else "E8F2FB"
                if date_heading or total
                else "F5F8FC"
                if cell.row % 2 == 0
                else "FFFFFF"
            )
            cell.fill = PatternFill("solid", fgColor=color)
            cell.font = Font(
                name="Calibri",
                size=11,
                color="FFFFFF" if header else "21344A",
                bold=header or total or date_heading,
            )
            cell.border = Border(bottom=line)
            cell.alignment = Alignment(
                horizontal="left" if cell.column == 2 else "center",
                vertical="center",
                wrap_text=True,
            )
            if 5 <= cell.row <= last_row:
                position = catalogue[cell.row - 5]
                key = days[cell.column - 10] if cell.column >= 10 else cell.column
                fill = fills.get((position["id"], key)) or fills.get((cell.row, key))
                if fill:
                    cell.fill = fill
                if cell.column in (5, 6, 8):
                    cell.number_format = AMOUNT_FORMAT
                elif cell.column in (4, 7) or cell.column >= 9:
                    cell.number_format = VOLUME_FORMAT
    for column, width in enumerate((5, 39, 9, 12, 12, 13, 12, 13, 13), 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    if catalogue:
        sheet.conditional_formatting.add(
            f"G5:G{last_row}",
            CellIsRule(
                operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor="FFE0D9")
            ),
        )
    sheet.freeze_panes = "J5"
    sheet.sheet_view.showGridLines = False
    return sheet


def verify_day_totals(content, day, payroll, positions):
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    journals = [sheet for sheet in book if is_journal(sheet)]
    if len(journals) == 1:
        sheet = journals[0]
        column = next((cell.column for cell in sheet[3] if str(cell.value)[:10] == day), None)
        if column:
            expected = [
                payroll["amount"],
                payroll["crew_count"],
                payroll["per_person"],
                payroll["extra_people"],
                payroll["extra_per_person"] if payroll["extra_people"] else None,
            ]
            actual = [sheet.cell(row, column).value for row in range(positions + 6, positions + 11)]
            if actual == expected:
                return
    if len(journals) > 1:
        total, row_count = Decimal(0), 0
        for sheet in journals:
            column = next((cell.column for cell in sheet[3] if str(cell.value)[:10] == day), None)
            count = sum(isinstance(cell.value, int) for cell in sheet["A"])
            row_count += count
            if not column or sheet.cell(count + 7, column).value != payroll["crew_count"]:
                break
            total += sum(
                Decimal(str(sheet.cell(row, column).value or 0))
                * Decimal(str(sheet.cell(row, 5).value or 0))
                for row in range(5, count + 5)
            )
        else:
            if (
                row_count == positions
                and float(total.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
                == payroll["amount"]
            ):
                return
    raise ValueError("Битрикс24 не подтвердил дневной расчёт на листе «Журнал работ».")
