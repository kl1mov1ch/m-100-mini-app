import base64
import io
import json
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, HTTPException, Request
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import column_index_from_string
from pydantic import BaseModel, Field

from . import bitrix, import_suggestions, store, tables
from .clock import now, today
from .imports import check_latest, directory, read_pending
from .synchronization import table_lock

router = APIRouter()


class CellChange(BaseModel):
    sheet: str
    cell: str = Field(pattern=r"^[A-Z]{1,3}[1-9]\d{0,6}$")
    value: str | float | None


class DuplicateChange(BaseModel):
    sheet: str
    date: date
    strategy: str = Field(pattern=r"^(sum|keep_first|rename)$")
    new_date: date | None = None


class DailyColumnChange(BaseModel):
    sheet: str
    column: str = Field(pattern=r"^[A-Z]{1,3}$")
    date: date
    strategy: str = Field(pattern=r"^(zero|remove|restore)$")


class TableChanges(BaseModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    edits: list[CellChange] = Field(default_factory=list, max_length=500)
    duplicates: list[DuplicateChange] = Field(default_factory=list, max_length=100)
    daily_columns: list[DailyColumnChange] = Field(default_factory=list, max_length=20)


def apply_changes(content, mappings, edits, duplicates, daily_columns=(), restoration=None):
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    catalogue = tables.extract(content, mappings)["positions"]
    changes = []
    for change in edits:
        if change.sheet not in workbook.sheetnames:
            raise ValueError("Лист не найден")
        sheet = workbook[change.sheet]
        cell = sheet[change.cell]
        descriptor = next(
            (mapping for mapping in mappings if mapping["name"] == change.sheet), None
        )
        if descriptor is None or cell.row <= descriptor["header_row"]:
            raise ValueError("Изменение заголовков выполняется через сопоставление столбцов")
        field = next(
            (field for field, column in descriptor["mapping"].items() if column == cell.column),
            None,
        )
        date_row = descriptor.get("date_row") or descriptor["header_row"]
        if field is None and tables.as_date(sheet.cell(date_row, cell.column).value):
            field = "daily"
        if field not in ("rate", "planned", "unit", "daily"):
            raise ValueError(
                "Эта ячейка не относится к расценке, плану, единице или дневному объёму"
            )
        value = change.value
        if field in ("rate", "planned", "daily"):
            value = tables.number(value)
            if value is None or value < 0:
                raise ValueError(f"{change.cell}: укажите число больше или равное нулю")
        else:
            value = str(value or "").strip()
            if not value or len(value) > 30 or value.startswith(("=", "+", "-", "@")):
                raise ValueError(f"{change.cell}: укажите корректную единицу измерения")
        changes.append(
            {
                "sheet": change.sheet,
                "cell": change.cell,
                "before": str(cell.value or ""),
                "after": value,
            }
        )
        cell.value = value
    for correction in duplicates:
        descriptor = next(
            (mapping for mapping in mappings if mapping["name"] == correction.sheet), None
        )
        if descriptor is None:
            raise ValueError("Лист не найден")
        sheet = workbook[correction.sheet]
        date_row = descriptor.get("date_row") or descriptor["header_row"]
        columns = [
            column
            for column in range(1, sheet.max_column + 1)
            if tables.as_date(sheet.cell(date_row, column).value) == correction.date.isoformat()
        ]
        if len(columns) < 2:
            raise ValueError("Повторяющихся столбцов этой даты уже нет. Перепроверьте файл.")
        if correction.strategy == "rename":
            if correction.new_date is None:
                raise ValueError("Выберите новую дату для последнего столбца")
            if any(
                tables.as_date(sheet.cell(date_row, column).value)
                == correction.new_date.isoformat()
                for column in range(1, sheet.max_column + 1)
            ):
                raise ValueError("Выбранная новая дата уже есть в таблице")
            cell = sheet.cell(date_row, columns[-1])
            cell.value = datetime.combine(correction.new_date, datetime.min.time())
            cell.number_format = "dd.mm.yyyy"
            changes.append(
                {
                    "sheet": sheet.title,
                    "cell": cell.coordinate,
                    "before": correction.date.isoformat(),
                    "after": correction.new_date.isoformat(),
                }
            )
            continue
        for position in catalogue:
            if position.get("source_sheet") != sheet.title:
                continue
            cells = [sheet.cell(position["source_row"], column) for column in columns]
            if any(str(cell.value or "").startswith("=") for cell in cells):
                raise ValueError(
                    "В дневных ячейках есть формулы. Для них выберите изменение даты вместо объединения."
                )
            if any(
                cell.value not in (None, "") and tables.number(cell.value) is None for cell in cells
            ):
                raise ValueError(
                    f"Строка {position['source_row']}: сначала исправьте нечисловые дневные объёмы"
                )
            if correction.strategy == "sum":
                values = [tables.number(cell.value) for cell in cells]
                merged = (
                    float(
                        sum(
                            (Decimal(str(value)) for value in values if value is not None),
                            Decimal(0),
                        )
                    )
                    if any(value is not None for value in values)
                    else None
                )
                cells[0].value = merged
                changes.append({"sheet": sheet.title, "cell": cells[0].coordinate, "after": merged})
            for cell in cells[1:]:
                cell.value = None
                changes.append({"sheet": sheet.title, "cell": cell.coordinate, "after": None})
        for column in columns[1:]:
            cell = sheet.cell(date_row, column)
            cell.value = None
            changes.append({"sheet": sheet.title, "cell": cell.coordinate, "after": None})
    if daily_columns:
        changes.extend(
            fix_daily_columns(
                workbook, content, mappings, catalogue, daily_columns, restoration or {}
            )
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), changes


def fix_daily_columns(workbook, content, mappings, catalogue, corrections, restoration):
    cached = tables.grid(content)
    changes = []
    for correction in corrections:
        descriptor = next(
            (mapping for mapping in mappings if mapping["name"] == correction.sheet), None
        )
        if descriptor is None or correction.sheet not in workbook:
            raise ValueError("Лист изменился. Прочитайте таблицу заново.")
        sheet = workbook[correction.sheet]
        column = column_index_from_string(correction.column)
        header = descriptor.get("date_row") or descriptor["header_row"]
        day = correction.date.isoformat()
        if column > sheet.max_column or tables.as_date(sheet.cell(header, column).value) != day:
            raise ValueError("Дата в столбце изменилась. Прочитайте таблицу заново.")
        if column in descriptor["mapping"].values():
            raise ValueError("Столбец используется в смете. Проверьте сопоставление.")
        if correction.strategy == "remove":
            sheet.column_dimensions[correction.column].hidden = True
            for row in range(header, sheet.max_row + 1):
                cell = sheet.cell(row, column)
                if not isinstance(cell, MergedCell) and cell.value is not None:
                    changes.append({"sheet": sheet.title, "cell": cell.coordinate, "after": None})
                    cell.value = None
            continue
        known = restoration.get(day, {})
        restored = 0
        for position in catalogue:
            if position["source_sheet"] != sheet.title:
                continue
            row = position["source_row"]
            cell = sheet.cell(row, column)
            if (
                tables.daily_quantity(cached[sheet.title].cell(row, column).value, position["unit"])
                is not None
            ):
                continue
            if correction.strategy == "restore" and position["id"] not in known:
                continue
            cell.value = known[position["id"]] if correction.strategy == "restore" else 0
            restored += 1
            changes.append({"sheet": sheet.title, "cell": cell.coordinate, "after": cell.value})
        if correction.strategy == "restore" and not restored:
            raise ValueError(
                "Нет сохранённых объёмов для этого столбца. Выберите нули или уберите колонку."
            )
    return changes


def prepare_corrections(original, metadata, body, restoration):
    try:
        updated, changes = apply_changes(
            original,
            metadata["sheets"],
            body.edits,
            body.duplicates,
            body.daily_columns,
            restoration,
        )
        from .workbook_calculation import recalculate

        updated = recalculate(
            updated, tables.extract(updated, metadata["sheets"])["positions"], metadata["sheets"]
        )
    except ValueError as error:
        raise HTTPException(422, str(error))
    return updated, changes


@router.post("/api/imports/edit")
async def edit_table(request: Request, body: TableChanges):
    metadata, original = read_pending(body.token, request.state.project["id"])
    if not body.edits and not body.duplicates and not body.daily_columns:
        raise HTTPException(422, "Выберите исправления")
    with store.connect() as database:
        webhook = store.setting(database, "webhook")
        file_id = int(store.setting(database, "file_id", "0"))
        pending = store.setting(database, "pending_import_token")
        restoration = {}
        if any(column.strategy == "restore" for column in body.daily_columns):
            positions = tables.extract(original, metadata["sheets"])["positions"]
            restoration = {
                column.date.isoformat(): import_suggestions.restore_day_values(
                    database, positions, column.date.isoformat()
                )
                for column in body.daily_columns
                if column.strategy == "restore"
            }
    remote = metadata["source"] == "bitrix"
    remote_id = (metadata.get("remote") or {}).get("file_id", file_id)
    if remote and (body.token != pending or file_id != int(remote_id or 0)):
        raise HTTPException(
            409, {"code": "workbook_changed", "message": "Открыта текущая проверка таблицы."}
        )
    if remote and not webhook:
        raise HTTPException(400, "Для записи добавьте вебхук с правом «Диск».")
    async with table_lock(request.state.project):
        if remote:
            try:
                latest, file_info = await bitrix.download_rest(webhook, file_id)
                check_latest(original, latest, metadata)
                updated, changes = prepare_corrections(latest, metadata, body, restoration)
                before_write, _ = await bitrix.download_rest(webhook, file_id)
                check_latest(latest, before_write, metadata)
                await bitrix.rest(
                    webhook,
                    "disk.file.uploadVersion",
                    {
                        "id": file_id,
                        "fileContent": [file_info["NAME"], base64.b64encode(updated).decode()],
                    },
                )
                verified, _ = await bitrix.download_rest(webhook, file_id)
                workbook = openpyxl.load_workbook(io.BytesIO(verified), data_only=False)
                for change in changes:
                    actual = workbook[change["sheet"]][change["cell"]].value
                    expected = change["after"]
                    if actual != expected and tables.as_date(actual) != expected:
                        raise ValueError(
                            "Битрикс не подтвердил исправленную ячейку " + change["cell"]
                        )
                updated = verified
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    502,
                    "Не удалось подтвердить изменения. Повторите чтение таблицы в приложении и проверьте выделенные ячейки.",
                )
        else:
            updated, changes = prepare_corrections(original, metadata, body, restoration)
        analysis = tables.extract(updated, metadata["sheets"])
        structural_warnings = [
            warning
            for warning in metadata["warnings"]
            if any(
                reason in warning["id"] for reason in ("ai-mapping", "ambiguous", "name-guessed")
            )
        ]
        metadata["warnings"] = structural_warnings + analysis["warnings"]
        metadata.pop("source_change", None)
        (directory() / f"{body.token}.xlsx").write_bytes(updated)
        (directory() / f"{body.token}.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        with store.connect() as database:
            store.set_setting(database, "connection_check", "null")
            store.set_setting(database, "bitrix_read_status", "null")
            database.execute(
                "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
                (
                    today(),
                    json.dumps(
                        {
                            "actor_name": request.state.user["name"],
                            "table_changes": changes,
                            "saved_to_source": remote,
                        },
                        ensure_ascii=False,
                    ),
                    now(),
                ),
            )
    from .imports import current_reconciliation

    return {
        "token": body.token,
        "name": metadata["name"],
        "source": metadata["source"],
        "saved_to_source": remote,
        **analysis,
        "warnings": metadata["warnings"],
        "reconciliation": current_reconciliation(analysis),
    }
