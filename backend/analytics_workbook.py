import io
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from math import ceil

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.axis import ChartLines, DateAxis
from openpyxl.chart.data_source import NumData, NumVal
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import to_excel

from . import orm_repository, postgres, store, workspaces
from .clock import today
from .report_notes import notes_in_period
from .workbook_notes import collect_notes, write_notes_sheet

NAVY = "21344A"
BLUE = "266BD3"
RED = "9F2028"
MONEY = '#,##0.00 "BYN"'
FIRST_DAY = 7


def report_filename(data, project_name=None, start=None, end=None):
    dates = sorted(row["date"] for row in data["rows"])
    first = (
        start.isoformat() if start else dates[0] if dates else end.isoformat() if end else today()
    )
    last = end.isoformat() if end else dates[-1] if dates else first
    period = first if first == last else first + "_" + last
    names = {row["project_name"] for row in data["rows"]}
    name = project_name or (
        next(iter(names))
        if len(names) == 1 and len(data.get("project_ids", names)) == 1
        else "Все объекты"
    )
    name = re.sub(r"[^\w .()–-]", "_", name, flags=re.UNICODE).strip(" .")[:80] or "Объекты"
    return f"Отчёт_{name}_{period}.xlsx"


def measure(value):
    # Keep the journal's eight decimal places when reading older SQLite floats.
    return Decimal(str(value or 0)).quantize(Decimal("0.00000001"))


def baselines(user, project_ids, final_day):
    through = date.fromisoformat(final_day)
    for project in workspaces.visible(user):
        if project["id"] not in project_ids:
            continue
        with store.connect(project["db_path"]) as database:
            if postgres.enabled():
                positions, recorded = orm_repository.work_history(database, through)
            else:
                positions = store.positions(database)
                recorded = database.execute(
                    "SELECT item_id,date,quantity FROM entries WHERE date<=? ORDER BY date",
                    (final_day,),
                )
            entries = defaultdict(dict)
            for item in recorded:
                entries[item["item_id"]][str(item["date"])] = measure(item["quantity"])
        yield project, positions, entries


def band(sheet, row, fill, *, color=NAVY, bold=False):
    for cell in row:
        cell.font = Font(name="Calibri", size=11, color=color, bold=bold)
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(
            vertical="center",
            horizontal="left" if cell.column <= 2 else "right",
            wrap_text=cell.column <= 2 or row[0].row == 4,
        )
        cell.border = Border(bottom=Side(style="hair", color="D6E2F0"))
        if isinstance(cell.value, str):
            cell.data_type = "s"


def mark_overrun(cell):
    cell.fill = PatternFill("solid", fgColor="FCE2E3")
    cell.font = Font(name="Calibri", size=11, color=RED, bold=True)


def write_totals(sheet, reports, days, *, combined=False):
    amounts = defaultdict(Decimal)
    crews = defaultdict(int)
    for report in reports:
        day = report["date"]
        amounts[day] += Decimal(str(report["amount"]))
        if report["positions"] and report["crew_count"]:
            crews[day] += report["crew_count"]
    sheet.append(
        [None, "Выработка", "BYN", None, float(sum(amounts.values())), None]
        + [float(amounts[day]) if day in amounts else None for day in days]
    )
    for cell in sheet[sheet.max_row][4:]:
        cell.number_format = MONEY
    band(sheet, sheet[sheet.max_row], "E9F1FA", bold=True)
    sheet.append(
        [None, "Человек за день", "чел.", None, sum(crews.values()) or None, None]
        + [crews.get(day) for day in days]
    )
    band(sheet, sheet[sheet.max_row], "E9F1FA", bold=True)
    if combined:
        sheet.cell(sheet.max_row - 1, 1, "Все объекты")
        sheet.cell(sheet.max_row, 1, "Все объекты")
    return amounts, crews


def write_position(sheet, position, entries, days, credit_changes, notes=None):
    plan = max(Decimal(0), measure(position["planned"]))
    rate = max(Decimal(0), Decimal(str(position["rate"] or 0)))
    actual = measure(position.get("baseline"))
    previous_credit = min(max(actual, 0), plan) * rate
    initial_credit = previous_credit
    red_days = set()
    for day, quantity in entries.items():
        actual += quantity
        credit = min(max(actual, 0), plan) * rate
        credit_changes[day] += credit - previous_credit
        previous_credit = credit
        if quantity > 0 and actual > plan:
            red_days.add(day)

    period_quantities = [entries.get(day) for day in days]
    if not any(period_quantities):
        return plan * rate, initial_credit
    excess = max(Decimal(0), actual - plan)
    sheet.append(
        [
            None,
            position["name"],
            position["unit"],
            float(plan),
            float(sum(q for q in period_quantities if q is not None)),
            float(excess) if excess else None,
        ]
        + [float(q) if q is not None else None for q in period_quantities]
    )
    row = sheet[sheet.max_row]
    band(sheet, row, "F4F8FC" if sheet.max_row % 2 == 0 else "FFFFFF")
    sheet.row_dimensions[sheet.max_row].height = min(
        66, 17 * ceil(max(1, len(position["name"])) / 54)
    )
    for cell in row[3:]:
        if cell.value is not None:
            scale = max(0, -measure(cell.value).normalize().as_tuple().exponent)
            cell.number_format = "#,##0" + ("." + "0" * scale if scale else "")
    if excess:
        mark_overrun(row[5])
    for column, day in enumerate(days, FIRST_DAY):
        if day in red_days:
            mark_overrun(row[column - 1])
        if notes and (note := notes.get(day)):
            row[column - 1].comment = Comment(note, "M-100")
    return plan * rate, initial_credit


def chart_sheet(book, days, amounts, crews, plan, initial_credit, credit_changes):
    sheet = book.create_sheet("Графики")
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:Q1")
    sheet["A1"] = "Выработка, бригада и прогресс"
    sheet["A1"].font = Font(name="Calibri", size=20, bold=True, color=NAVY)
    sheet.row_dimensions[1].height = 34
    if not days:
        sheet["A3"] = "За выбранный период отчётов нет."
        return

    data_column = 27
    for col, label in enumerate(("Дата", "Выработка", "Человек", "Прогресс"), data_column):
        sheet.cell(1, col, label)
        sheet.column_dimensions[get_column_letter(col)].hidden = True
    changes = iter(sorted(credit_changes.items()))
    change = next(changes, None)
    credited = initial_credit
    for row, day in enumerate(days, 2):
        while change and change[0] <= day:
            credited += change[1]
            change = next(changes, None)
        sheet.cell(row, data_column, date.fromisoformat(day)).number_format = "dd.mm.yy"
        sheet.cell(row, data_column + 1, float(amounts.get(day, 0))).number_format = MONEY
        sheet.cell(row, data_column + 2, crews.get(day))
        if plan:
            sheet.cell(row, data_column + 3, float(credited / plan)).number_format = "0.0%"

    for col in range(1, 25):
        sheet.column_dimensions[get_column_letter(col)].width = 10
    span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days
    definitions = [
        (BarChart, 1, "Выработка по дням", "BYN", BLUE, "#,##0", "A3"),
        (BarChart, 2, "Людей за день по заполненным отчётам", "Человек", "188A72", "0", "A26"),
    ]
    if plan:
        definitions.append(
            (
                LineChart,
                3,
                "Накопленный прогресс в пределах сметы",
                "Доля сметы",
                "3E59A9",
                "0%",
                "A49",
            )
        )
    for chart_type, offset, title, label, color, fmt, anchor in definitions:
        chart = chart_type()
        chart.title = title
        chart.title.overlay = False
        chart.style = 10
        chart.width = 30
        chart.height = 11.5
        chart.legend = None
        chart.display_blanks = "gap"
        chart.visible_cells_only = False
        chart.y_axis.title = label
        chart.y_axis.title.overlay = False
        chart.y_axis.axPos = "l"
        chart.y_axis.delete = False
        chart.y_axis.tickLblPos = "nextTo"
        chart.y_axis.numFmt = fmt
        chart.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties())
        chart.y_axis.majorGridlines.spPr.line.solidFill = "D6E2F0"
        chart.y_axis.scaling.min = 0
        if chart_type is BarChart:
            chart.type = "col"
            chart.gapWidth = 90
        else:
            chart.y_axis.scaling.max = 1
            chart.y_axis.majorUnit = 0.2
        chart.x_axis = DateAxis(axId=500, crossAx=chart.y_axis.axId, axPos="b")
        chart.y_axis.crossAx = 500
        chart.x_axis.delete = False
        chart.x_axis.tickLblPos = "low"
        chart.x_axis.number_format = "dd.mm.yy"
        chart.x_axis.majorTimeUnit = "days"
        chart.x_axis.majorUnit = max(1, ceil(span / 12))
        chart.add_data(
            Reference(sheet, min_col=data_column + offset, min_row=1, max_row=len(days) + 1),
            titles_from_data=True,
        )
        chart.set_categories(
            Reference(sheet, min_col=data_column, min_row=2, max_row=len(days) + 1)
        )
        series = chart.series[0]
        series.cat.numRef.numCache = NumData(
            formatCode="dd.mm.yy",
            ptCount=len(days),
            pt=[
                NumVal(idx=index, v=to_excel(date.fromisoformat(day)))
                for index, day in enumerate(days)
            ],
        )
        values = [sheet.cell(row, data_column + offset).value for row in range(2, len(days) + 2)]
        series.val.numRef.numCache = NumData(
            formatCode=fmt,
            ptCount=len(days),
            pt=[
                NumVal(idx=index, v=value)
                for index, value in enumerate(values)
                if value is not None
            ],
        )
        if chart_type is BarChart:
            series.graphicalProperties.solidFill = color
            series.graphicalProperties.line.noFill = True
        else:
            series.smooth = False
            series.graphicalProperties.line.solidFill = color
            series.graphicalProperties.line.width = 28575
            if len(days) < 20:
                series.marker.symbol = "circle"
                series.marker.size = 5
                series.marker.graphicalProperties.solidFill = color
                series.marker.graphicalProperties.line.noFill = True
        sheet.add_chart(chart, anchor)
    sheet.print_area = f"A1:Q{71 if plan else 48}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def export_workbook(user, data, *, with_charts=True):
    book = Workbook()
    sheet = book.active
    sheet.title = "Работы по дням"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "C5"
    sheet.merge_cells("A1:F1")
    sheet["A1"] = "Журнал работ"
    sheet["A1"].font = Font(name="Calibri", size=21, bold=True, color=NAVY)
    sheet.row_dimensions[1].height = 34
    sheet.merge_cells("A2:F2")
    sheet["A2"] = (
        "Красная ячейка дня означает, что после этих работ превышена смета. "
        "В строке «Человек за день» итог за период указан в человеко-днях."
    )
    sheet["A2"].font = Font(name="Calibri", size=11, color="526781")
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[2].height = 32
    days = sorted(
        {report["date"] for report in data["rows"] if report["positions"] or report.get("revision")}
    )
    for col, width in enumerate([24, 52, 9, 12, 16, 16] + [13] * len(days), 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    for col, label in enumerate(
        ["Объект", "Работа", "Ед.", "По смете", "За период", "Сверх сметы"]
        + [date.fromisoformat(day) for day in days],
        1,
    ):
        cell = sheet.cell(4, col, label)
        if col >= FIRST_DAY:
            cell.number_format = "dd.mm.yy"
    band(sheet, sheet[4], NAVY, color="FFFFFF", bold=True)
    sheet.row_dimensions[4].height = 31
    sheet.print_title_rows = "1:4"

    reports = defaultdict(list)
    for row in data["rows"]:
        if row["positions"] or row.get("revision"):
            reports[row["project_id"]].append(row)
    plan = initial_credit = Decimal(0)
    credit_changes = defaultdict(Decimal)
    amounts, crews = {}, {}
    work_notes = []
    if days:
        if len(reports) > 1:
            amounts, crews = write_totals(sheet, data["rows"], days, combined=True)
        final_day = data.get("period_end") or days[-1]
        for project, positions, entries in baselines(user, set(data["project_ids"]), final_day):
            project_reports = reports.get(project["id"], [])
            notes_by_position = defaultdict(dict)
            names = {position["id"]: position["name"] for position in positions}
            allowed_days = {item["date"] for item in project_reports}
            with store.connect(project["db_path"]) as db:
                work_notes.extend(
                    collect_notes(
                        db,
                        project["name"],
                        positions,
                        start=days[0],
                        end=days[-1],
                        days=allowed_days,
                    )
                )
                for day, note, line_notes in notes_in_period(db, days[0], days[-1]):
                    if day not in allowed_days:
                        continue
                    for item_id, text in line_notes.items():
                        if item_id in names:
                            notes_by_position[item_id][day] = text
            if project_reports:
                sheet.append([project["name"]])
                row = sheet.max_row
                sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
                band(sheet, sheet[row], "DCE9F8", bold=True)
                sheet.row_dimensions[row].height = 26
                totals = write_totals(sheet, project_reports, days)
                if len(reports) == 1:
                    amounts, crews = totals
            for position in positions:
                p_plan, p_credit = write_position(
                    sheet,
                    position,
                    entries[position["id"]],
                    days,
                    credit_changes,
                    notes_by_position.get(position["id"]),
                )
                plan += p_plan
                initial_credit += p_credit
    else:
        sheet["A5"] = "Нет работ за выбранный период"
        for project in workspaces.visible(user):
            if project["id"] in data["project_ids"]:
                with store.connect(project["db_path"]) as db:
                    work_notes.extend(collect_notes(db, project["name"], [], days=set()))
    write_notes_sheet(book, work_notes)
    if with_charts:
        chart_sheet(book, days, amounts, crews, plan, initial_credit, credit_changes)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
