import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Font, PatternFill

from . import store, workspaces
from .clock import today


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


def add_dashboard(workbook, user, data):
    rows = data["rows"]
    visible = {project["id"]: project for project in workspaces.visible(user)}
    selected = sorted(data.get("project_ids", {row["project_id"] for row in rows}))
    days = sorted({row["date"] for row in rows})
    final_day = data.get("period_end") or (days[-1] if days else today())
    daily_amount = defaultdict(Decimal)
    daily_workers = defaultdict(int)
    for row in rows:
        daily_amount[row["date"]] += Decimal(str(row["amount"]))
        daily_workers[row["date"]] += row["crew_count"] or 0
    projects = []
    for ident in selected:
        with store.connect(visible[ident]["db_path"]) as database:
            positions = store.positions(database)
            entries = [
                dict(row) for row in database.execute("SELECT item_id,date,quantity FROM entries")
            ]
        projects.append((visible[ident], positions, entries))
    planned_total = sum(
        max(0, float(p["planned"])) * max(0, float(p["rate"]))
        for _, positions, _ in projects
        for p in positions
    )

    def progress_on(day):
        credited = 0
        for _, positions, entries in projects:
            completed = defaultdict(float)
            for entry in entries:
                if entry["date"] <= day:
                    completed[entry["item_id"]] += float(entry["quantity"])
            for position in positions:
                quantity = float(position.get("baseline", 0)) + completed[position["id"]]
                credited += min(max(0, quantity), max(0, float(position["planned"]))) * max(
                    0, float(position["rate"])
                )
        return credited

    credited = progress_on(final_day)
    sheet = workbook.create_sheet("Сводка", 0)
    sheet.sheet_view.showGridLines = False
    for column in "ABCDEFGH":
        sheet.column_dimensions[column].width = 15
    sheet.merge_cells("A1:H1")
    sheet["A1"] = "М100 · ОТЧЁТ ПО РАБОТАМ"
    sheet["A1"].font = Font(name="Calibri", size=20, bold=True, color="17365D")
    sheet.row_dimensions[1].height = 36
    sheet.merge_cells("A2:H2")
    sheet["A2"] = (
        " · ".join(sorted({project["name"] for project, _, _ in projects}))
        or "Нет отчётов за выбранный период"
    )
    sheet["A2"].data_type = "s"
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[2].height = 32
    sheet.merge_cells("A3:H3")
    sheet["A3"] = (
        f"Период: {days[0] if days else '—'} — {final_day} · Валюта: белорусский рубль (Br)"
    )
    metrics = [
        ("A", "B", "Выработка за период", data["summary"]["amount"], '#,##0.00 "Br"'),
        ("C", "D", "Смета объектов", planned_total, '#,##0.00 "Br"'),
        (
            "E",
            "F",
            "Прогресс по смете",
            credited / planned_total if planned_total else None,
            "0.0%",
        ),
        ("G", "H", "Человеко-дней", data["summary"]["worker_days"], "0"),
    ]
    for left, right, label, value, number_format in metrics:
        sheet.merge_cells(f"{left}5:{right}5")
        sheet.merge_cells(f"{left}6:{right}6")
        sheet[f"{left}5"] = label
        sheet[f"{left}6"] = value if value is not None else "Нет расценок"
        for row in (5, 6):
            cell = sheet[f"{left}{row}"]
            cell.fill = PatternFill("solid", fgColor="EAF1FA")
            cell.font = Font(
                name="Calibri", size=12 if row == 5 else 19, bold=row == 6, color="17365D"
            )
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.number_format = number_format
    sheet.row_dimensions[5].height = 28
    sheet.row_dimensions[6].height = 34
    sheet.merge_cells("A8:H8")
    sheet["A8"] = (
        "Прогресс = стоимость выполненного в пределах сметы / стоимость сметы. Это не оценка загрузки бригады."
    )
    sheet["A8"].font = Font(size=10, color="617086")
    sheet["A8"].alignment = Alignment(wrap_text=True)
    sheet.row_dimensions[8].height = 30
    sheet.merge_cells("A9:H9")
    sheet["A9"] = (
        "Учтены начальные объёмы из таблицы. Перерасход показан отдельно. Позиции без расценки не входят в процент."
    )
    sheet["A9"].font = Font(size=10, color="617086")
    sheet["A9"].alignment = Alignment(wrap_text=True)
    sheet.row_dimensions[9].height = 30
    sheet.append([])
    header = 29
    for col, value in enumerate(
        [
            "Дата",
            "За день, Br",
            "Накоплено за период, Br",
            "Работников",
            "Прогресс по смете",
            "Выполнено по смете, Br",
        ],
        1,
    ):
        sheet.cell(header, col, value)
    cumulative = Decimal(0)
    for row_number, day in enumerate(days, header + 1):
        cumulative += daily_amount[day]
        completed = progress_on(day)
        for col, value in enumerate(
            [
                date.fromisoformat(day),
                float(daily_amount[day]),
                float(cumulative),
                daily_workers[day] or None,
                completed / planned_total if planned_total else None,
                completed,
            ],
            1,
        ):
            sheet.cell(row_number, col, value)
        sheet.cell(row_number, 1).number_format = "dd.mm.yyyy"
        for col in (2, 3, 6):
            sheet.cell(row_number, col).number_format = '#,##0.00 "Br"'
        sheet.cell(row_number, 5).number_format = "0.0%"
    if days:
        for chart_class, column, title, anchor in [
            (BarChart, 2, "Выработка по дням, Br", "A11"),
            (LineChart, 5, "Прогресс относительно сметы", "E11"),
        ]:
            chart = chart_class()
            chart.title = title
            chart.style = 13
            chart.width = 11.3
            chart.height = 8.3
            chart.legend = None
            chart.add_data(
                Reference(sheet, min_col=column, min_row=header, max_row=header + len(days)),
                titles_from_data=True,
            )
            chart.set_categories(
                Reference(sheet, min_col=1, min_row=header + 1, max_row=header + len(days))
            )
            chart.x_axis.title = "Дата"
            chart.y_axis.title = "Br" if column == 2 else "Доля сметы"
            chart.y_axis.numFmt = "#,##0" if column == 2 else "0%"
            chart.y_axis.scaling.min = 0
            if column == 5:
                chart.y_axis.scaling.max = 1
            sheet.add_chart(chart, anchor)
    for row in sheet.iter_rows(min_row=header, max_row=max(header, sheet.max_row)):
        sheet.row_dimensions[row[0].row].height = 36 if row[0].row == header else 25
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.row == header:
                cell.fill = PatternFill("solid", fgColor="2563EB")
                cell.font = Font(bold=True, color="FFFFFF")
    sheet.freeze_panes = "B30"
    if days:
        sheet.auto_filter.ref = f"A29:F{29 + len(days)}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_options.horizontalCentered = True
    sheet.print_area = f"A1:H{max(29, sheet.max_row)}"
    progress = workbook.create_sheet("Прогресс объектов")
    progress.append(
        [
            "Объект",
            "Смета, Br",
            "В пределах сметы, Br",
            "Осталось, Br",
            "Прогресс",
            "Перерасход, Br",
            "Без расценки, позиций",
            "На дату",
        ]
    )
    for project, positions, entries in projects:
        quantities = defaultdict(float)
        for entry in entries:
            if entry["date"] <= final_day:
                quantities[entry["item_id"]] += float(entry["quantity"])
        plan = done = excess = 0
        for p in positions:
            rate = max(0, float(p["rate"]))
            volume = max(0, float(p["planned"]))
            actual = max(0, float(p.get("baseline", 0)) + quantities[p["id"]])
            plan += volume * rate
            done += min(actual, volume) * rate
            excess += max(0, actual - volume) * rate
        progress.append(
            [
                project["name"],
                plan,
                done,
                max(0, plan - done),
                done / plan if plan else None,
                excess,
                sum(float(p["rate"]) <= 0 for p in positions),
                date.fromisoformat(final_day),
            ]
        )
    progress.conditional_formatting.add(
        f"E2:E{max(2, progress.max_row)}",
        DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="3D9970"),
    )
    workbook.active = 0
    return progress
