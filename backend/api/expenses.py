import base64
import io
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4
from zipfile import BadZipFile

import httpx
import openpyxl
from fastapi import APIRouter, HTTPException, Request
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import bitrix, store, workbook_revision
from ..expense_drafts import MAX_LINES, parse_expenses
from ..expense_rules import extra_position
from ..reporting import ai_settings
from ..synchronization import table_lock
from ..workbook_expenses import with_expenses
from ..workbook_journal import format_journal, is_journal
from .objects import owned_object

router = APIRouter(prefix="/api/object/expenses")


class ExpenseValues(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=300)
    unit: str = Field(min_length=1, max_length=24)
    quantity: Decimal = Field(gt=0, le=1000000, decimal_places=4)
    rate: Decimal = Field(ge=0, le=1000000, decimal_places=4)
    note: str = Field(default="", max_length=500)


class ExpenseInput(ExpenseValues):
    id: str | None = Field(default=None, max_length=32)
    revision: int | None = Field(default=None, ge=1)


class ExpenseBatchItem(ExpenseValues):
    draft_id: UUID


class ExpenseBatch(BaseModel):
    rows: list[ExpenseBatchItem] = Field(min_length=1, max_length=MAX_LINES)


class ExpenseText(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


def expense_data(db, request):
    rows = json.loads(store.setting(db, "extra_expenses", "[]"))
    total = sum((Decimal(row["amount"]) for row in rows), Decimal(0))
    user = request.state.user
    connected = (
        store.setting(db, "source") == "bitrix"
        and bool(store.setting(db, "webhook"))
        and store.setting(db, "file_id", "0") not in {"", "0"}
    )
    return {
        "rows": sorted(rows, key=lambda row: row["date"], reverse=True),
        "total": str(total),
        "templates": [
            {key: row[key] for key in ("id", "name", "unit", "rate")}
            for row in store.positions(db)
            if extra_position(row)
        ],
        "can_edit": user["role"] == "master"
        and user["telegram_id"] == request.state.project["owner_id"],
        "can_sync": connected,
        "sync_status": store.setting(db, "extra_expenses_sync", "local") if connected else "local",
    }


@router.get("")
def list_expenses(request: Request):
    with store.connect() as db:
        return expense_data(db, request)


def expense_workbook(content, rows, mappings):
    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    try:
        journal_exists = any(is_journal(sheet) for sheet in book)
    finally:
        book.close()
    if not journal_exists:
        parsed = bitrix.read_workbook(content, mappings)
        content = format_journal(
            content,
            parsed["positions"],
            parsed["entries"],
            parsed.get("crew_by_day", {}),
            [],
            mappings,
        )
    return with_expenses(content, rows)


async def sync_expenses(request):
    with store.connect() as db:
        rows = json.loads(store.setting(db, "extra_expenses", "[]"))
        webhook = store.setting(db, "webhook")
        file_id = int(store.setting(db, "file_id", "0") or 0)
        mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
        connected = store.setting(db, "source") == "bitrix" and webhook and file_id
    status = "local"
    if connected and rows:
        status = "pending"
        try:
            before, meta = await bitrix.download_rest(webhook, file_id)
            patched = await run_in_threadpool(expense_workbook, before, rows, mappings)
            if not await run_in_threadpool(workbook_revision.changes, before, patched):
                status = "synced"
            else:
                latest, _ = await bitrix.download_rest(webhook, file_id)
                if await run_in_threadpool(workbook_revision.changes, before, latest):
                    raise ValueError("Таблица изменилась во время сохранения")
                uploaded = await bitrix.rest(
                    webhook,
                    "disk.file.uploadVersion",
                    {
                        "id": file_id,
                        "fileContent": [meta["NAME"], base64.b64encode(patched).decode()],
                    },
                )
                if not uploaded:
                    raise ValueError("Загрузка не подтверждена")
                verified, _ = await bitrix.download_rest(webhook, file_id)
                if not await run_in_threadpool(workbook_revision.changes, patched, verified):
                    status = "synced"
        except (httpx.HTTPError, ValueError, OSError, KeyError, BadZipFile, InvalidFileException):
            # Keep the local write and allow a retry even after a lost upload response.
            status = "pending"
    with store.connect() as db:
        store.set_setting(db, "extra_expenses_sync", status)
        return expense_data(db, request)


def stored_expense(body, ident, revision=1):
    if not body.name.strip() or not body.unit.strip():
        raise HTTPException(422, "Укажите название и единицу измерения")
    amount = (body.quantity * body.rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "id": ident,
        "revision": revision,
        "date": body.date.isoformat(),
        "name": body.name.strip(),
        "unit": body.unit.strip(),
        "quantity": str(body.quantity),
        "rate": str(body.rate),
        "amount": str(amount),
        "note": body.note.strip(),
    }


def update_ledger(db, rows):
    if len(rows) > 5000:
        raise HTTPException(422, "В объекте уже 5000 расходов")
    store.set_setting(db, "extra_expenses", json.dumps(rows, ensure_ascii=False))
    store.set_setting(db, "extra_expenses_sync", "pending")


@router.post("/parse")
async def draft_expenses(request: Request, body: ExpenseText):
    owned_object(request)
    with store.connect() as db:
        settings = ai_settings(db)
    try:
        return {"rows": await parse_expenses(body.text, settings)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/batch")
async def save_expense_batch(request: Request, body: ExpenseBatch):
    project = owned_object(request)
    incoming = {item.draft_id.hex: stored_expense(item, item.draft_id.hex) for item in body.rows}
    if len(incoming) != len(body.rows):
        raise HTTPException(422, "В списке повторяется черновик")
    async with table_lock(project):
        with store.connect() as db:
            rows = json.loads(store.setting(db, "extra_expenses", "[]"))
            existing_ids = {row["id"] for row in rows}
            new_rows = [row for ident, row in incoming.items() if ident not in existing_ids]
            if new_rows:
                update_ledger(db, rows + new_rows)
            else:
                current = expense_data(db, request)
                if current["sync_status"] != "pending":
                    return current
        return await sync_expenses(request)


@router.post("")
async def save_expense(request: Request, body: ExpenseInput):
    project = owned_object(request)
    async with table_lock(project):
        with store.connect() as db:
            rows = json.loads(store.setting(db, "extra_expenses", "[]"))
            current = next((row for row in rows if row["id"] == body.id), None)
            if body.id and not current:
                raise HTTPException(404, "Расход не найден")
            if current and current["revision"] != body.revision:
                raise HTTPException(409, "Расход уже изменён. Обновите список")
            row = stored_expense(
                body,
                current["id"] if current else uuid4().hex,
                current["revision"] + 1 if current else 1,
            )
            if current:
                rows[rows.index(current)] = row
            else:
                rows.append(row)
            update_ledger(db, rows)
        return await sync_expenses(request)


@router.post("/sync")
async def retry_expenses(request: Request):
    async with table_lock(owned_object(request)):
        return await sync_expenses(request)
