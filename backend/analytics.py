import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Request
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import store, workspaces
from .analytics_workbook import export_workbook, report_filename
from .report_downloads import report_export
from .reporting import history

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
    work_dates = set()
    for project in projects:
        with store.connect(project["db_path"]) as database:
            for row in history(database):
                if row["positions"] > 0:
                    work_dates.add(row["date"])
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
    return {
        "rows": rows,
        "work_dates": sorted(work_dates),
        "summary": summary,
        "project_ids": [project["id"] for project in projects],
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
    }


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
    project_name = workspaces.project(user, project_id)["name"] if project_id else None
    export_data = collect(user, start, end, project_id, owner_id, sort)

    def render(current_user):
        return export_workbook(
            current_user, collect(current_user, start, end, project_id, owner_id, sort)
        )

    return report_export(
        user,
        report_filename(export_data, project_name, start, end),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        render,
        prepare,
    )
