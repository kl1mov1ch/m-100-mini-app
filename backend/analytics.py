import io
import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Request
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import store, workspaces
from .report_downloads import report_export
from .reporting import get_report, history

router = APIRouter()


def collect(user, start=None, end=None, project_id=None, owner_id=None, sort="date_desc"):
    if start and end and start > end:
        raise HTTPException(422, "Начальная дата должна быть раньше конечной")
    projects = workspaces.visible(user)
    if project_id:
        workspaces.project(user, project_id)
        projects = [project for project in projects if project["id"] == project_id]
    if owner_id:
        projects = [project for project in projects if project["owner_id"] == owner_id]
    rows = []
    for project in projects:
        with store.connect(project["db_path"]) as database:
            for row in history(database):
                if (
                    start
                    and row["date"] < start.isoformat()
                    or end
                    and row["date"] > end.isoformat()
                ):
                    continue
                rows.append(
                    {
                        **row,
                        "sync_error": row["sync_error"] if user["role"] == "master" else "",
                        "project_id": project["id"],
                        "project_name": project["name"],
                        "owner_id": project["owner_id"],
                        "owner_name": project["owner_name"],
                    }
                )
    sorting = {
        "date_desc": ("date", True),
        "date_asc": ("date", False),
        "amount_desc": ("amount", True),
        "amount_asc": ("amount", False),
    }
    key, reverse = sorting.get(sort, sorting["date_desc"])
    rows.sort(key=lambda row: (row[key], row["project_name"]), reverse=reverse)
    amount = sum((Decimal(str(row["amount"])) for row in rows), Decimal(0))
    worker_days = sum((row["crew_count"] or 0) for row in rows if row["positions"])
    known_amount = sum(
        (Decimal(str(row["amount"])) for row in rows if row["crew_count"] and row["positions"]),
        Decimal(0),
    )
    summary = {
        "amount": float(amount),
        "reports": len(rows),
        "confirmed": sum(row["revision"] > 0 for row in rows),
        "positions": sum(row["positions"] for row in rows),
        "projects": len({row["project_id"] for row in rows}),
        "days": len({row["date"] for row in rows if row["positions"]}),
        "worker_days": worker_days,
        "per_person": float(
            (known_amount / worker_days).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        )
        if worker_days
        else None,
        "pending": sum(row["revision"] > 0 and row["sync_status"] != "synced" for row in rows),
    }
    return {"rows": rows, "summary": summary}


@router.get("/api/analytics")
def report_list(
    request: Request,
    start: date | None = None,
    end: date | None = None,
    project_id: str | None = None,
    owner_id: str | None = None,
    sort: str = "date_desc",
):
    return collect(request.state.user, start, end, project_id, owner_id, sort)


def style_sheet(sheet, header, widths, money_columns=()):
    sheet.freeze_panes = f"A{header + 1}"
    sheet.auto_filter.ref = f"A{header}:{get_column_letter(sheet.max_column)}{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    line = Side(style="hair", color="DDE7F3")
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in sheet.iter_rows(min_row=header):
        height = 26
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = Border(bottom=line)
            cell.font = Font(name="Calibri", size=11, color="203958")
            if cell.row == header:
                cell.fill = PatternFill("solid", fgColor="2563EB")
                cell.font = Font(name="Calibri", size=11, color="FFFFFF", bold=True)
                height = 36
            else:
                cell.fill = PatternFill(
                    "solid", fgColor="F0F5FC" if cell.row % 2 == 0 else "FFFFFF"
                )
                if cell.column in money_columns:
                    cell.number_format = '#,##0.00 "BYN"'
                if isinstance(cell.value, str):
                    height = max(
                        height,
                        16 * math.ceil(len(cell.value) / max(10, widths[cell.column - 1] - 2)),
                    )
                    if cell.value.startswith(("=", "+", "-", "@")):
                        cell.data_type = "s"
        sheet.row_dimensions[row[0].row].height = height
    sheet.print_title_rows = f"{header}:{header}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def export_workbook(user, data):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Общий отчёт"
    sheet.merge_cells("A1:H1")
    sheet["A1"] = "ЖУРНАЛ РАБОТ · СВОДНЫЙ ОТЧЁТ"
    sheet["A1"].font = Font(size=19, bold=True, color="1D4ED8")
    sheet.row_dimensions[1].height = 38
    sheet.append(
        [
            "Общая выработка, BYN",
            "Отчётов",
            "Работ",
            "Объектов",
            "Дней",
            "Человеко-дней",
            "Средняя доля, BYN",
            "Ожидают Битрикс",
        ]
    )
    summary = data["summary"]
    sheet.append(
        [
            summary[key]
            for key in (
                "amount",
                "reports",
                "positions",
                "projects",
                "days",
                "worker_days",
                "per_person",
                "pending",
            )
        ]
    )
    for cell in sheet[2]:
        cell.fill = PatternFill("solid", fgColor="DBEAFE")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.font = Font(bold=True, color="1E40AF")
    sheet.row_dimensions[2].height = 36
    for column in (1, 7):
        sheet.cell(3, column).number_format = '#,##0.00 "BYN"'
    sheet.append([])
    sheet.append(
        [
            "Дата",
            "Объект",
            "Мастер",
            "Работ",
            "Работников",
            "Сумма, BYN",
            "На человека, BYN",
            "Состояние",
        ]
    )
    statuses = {
        "synced": "Отправлен в Битрикс",
        "pending": "Ожидает Битрикс",
        "error": "Ошибка отправки",
        "imported": "Из таблицы",
        "local": "Сохранён",
    }
    details = workbook.create_sheet("Выполненные работы")
    details.append(
        ["Дата", "Объект", "Мастер", "Работа", "Ед.", "Объём", "Расценка, BYN", "Стоимость, BYN"]
    )
    projects = {project["id"]: project for project in workspaces.visible(user)}
    for row in data["rows"]:
        sheet.append(
            [
                datetime_label(row["date"]),
                row["project_name"],
                row["owner_name"],
                row["positions"],
                row["crew_count"],
                row["amount"],
                row["per_person"] if row["crew_count"] else None,
                statuses.get(row["sync_status"], row["sync_status"]),
            ]
        )
        with store.connect(projects[row["project_id"]]["db_path"]) as database:
            report = get_report(database, row["date"])
            catalog = {position["id"]: position for position in store.positions(database)}
            for line in report["lines"]:
                position = catalog[line["item_id"]]
                cost = (Decimal(str(line["quantity"])) * Decimal(str(position["rate"]))).quantize(
                    Decimal(".01"), rounding=ROUND_HALF_UP
                )
                details.append(
                    [
                        datetime_label(row["date"]),
                        row["project_name"],
                        row["owner_name"],
                        position["name"],
                        position["unit"],
                        line["quantity"],
                        position["rate"],
                        float(cost),
                    ]
                )
    style_sheet(sheet, 5, [19, 36, 26, 12, 15, 21, 24, 27], (6, 7))
    style_sheet(details, 1, [17, 30, 24, 65, 9, 15, 21, 23], (7, 8))
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def datetime_label(value):
    return date.fromisoformat(value).strftime("%d.%m.%Y")


@router.get("/api/analytics/export.xlsx")
def export(
    request: Request,
    start: date | None = None,
    end: date | None = None,
    project_id: str | None = None,
    owner_id: str | None = None,
    sort: str = "date_desc",
    prepare: bool = False,
):
    user = request.state.user
    if start and end and start > end:
        raise HTTPException(422, "Начальная дата должна быть раньше конечной")
    if project_id:
        workspaces.project(user, project_id)

    def render(current_user):
        return export_workbook(
            current_user, collect(current_user, start, end, project_id, owner_id, sort)
        )

    return report_export(
        user,
        "work-reports.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        render,
        prepare,
    )
