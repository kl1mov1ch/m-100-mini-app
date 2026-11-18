from datetime import date
from math import ceil

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from . import store
from .report_notes import notes_in_period

MARKER = "M100 • Примечания"


def collect_notes(db, project_name, positions, *, start="0000-00-00", end="9999-12-31", days=None):
    names = {position["id"]: position["name"] for position in positions}
    rows = []
    if note := store.setting(db, "object_note"):
        rows.append((None, "Объект", project_name, note))
    for day, note, work_notes in notes_in_period(db, start, end):
        if days is not None and day not in days:
            continue
        if note:
            rows.append((day, "За день", project_name, note))
        rows.extend(
            (day, "Работа", f"{project_name} · {names[item_id]}", text)
            for item_id, text in work_notes.items()
            if item_id in names
        )
    return rows


def write_notes_sheet(book, rows):
    existing = next((sheet for sheet in book if sheet["A1"].value == MARKER), None)
    if existing is not None:
        book.remove(existing)
    if not rows:
        return
    sheet = book.create_sheet("Примечания")
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = "266BD3"
    sheet.freeze_panes = "C3"
    sheet.append([MARKER])
    sheet.merge_cells("A1:D1")
    sheet.append(["Дата", "К чему", "Объект / работа", "Примечание"])
    for col, width in zip("ABCD", (14, 14, 44, 78)):
        sheet.column_dimensions[col].width = width
    for row, height in ((1, 32), (2, 25)):
        sheet.row_dimensions[row].height = height
        for cell in sheet[row]:
            cell.fill = PatternFill("solid", fgColor="21344A" if row == 1 else "345477")
            cell.font = Font(name="Calibri", size=16 if row == 1 else 11, bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center", indent=1)
    for index, (day, category, subject, note) in enumerate(rows, 3):
        sheet.append([date.fromisoformat(day) if day else "—", category, subject, note])
        for cell in sheet[index]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.fill = PatternFill("solid", fgColor="F3F7FC" if index % 2 else "FFFFFF")
            cell.font = Font(name="Calibri", size=11, color="21344A", bold=cell.column == 2)
            cell.border = Border(bottom=Side(style="hair", color="D7E2EF"))
            cell.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
        sheet.cell(index, 1).number_format = "dd.mm.yyyy"
        lines = max(
            ceil(len(subject) / 39), sum(max(1, ceil(len(line) / 70)) for line in note.splitlines())
        )
        sheet.row_dimensions[index].height = min(409, max(28, 9 + lines * 16))
    sheet.auto_filter.ref = f"A2:D{sheet.max_row}"
    sheet.print_title_rows = "1:2"
    sheet.page_setup.orientation = "landscape"
