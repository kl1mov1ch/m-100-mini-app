import base64
import hashlib
import io
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import openpyxl
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .. import bitrix, postgres, profile_webhooks, store, tables, workspaces
from ..analytics import style_sheet
from ..naming import unique_project_name
from ..orm_models import Position, Project, ProjectSetting, User
from ..workbook_journal import format_journal, is_journal, journal_row
from .aggregation import notes_with_sources
from .normalization import financial_summary
from .repository import DocumentJob, folder, owned, public, session, version

router = APIRouter(prefix="/api/documents")


def row_hash(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def ensure_empty(content):
    book = openpyxl.load_workbook(io.BytesIO(content))
    try:
        for sheet in book:
            if sheet.max_row * sheet.max_column > 3000000:
                raise ValueError("Выберите новый пустой XLSX-файл")
            if (
                sheet._charts
                or sheet._images
                or any(
                    cell.value is not None and str(cell.value).strip()
                    for row in sheet
                    for cell in row
                )
            ):
                raise ValueError("В файле уже есть данные. Выберите отдельный пустой XLSX-файл.")
    finally:
        book.close()


def make_workbook(content, rows):
    positions = [
        {
            "id": "pdf-" + row["id"],
            "name": row["name"],
            "section": " · ".join(
                filter(None, [row["category"], row.get("section"), row.get("subsection")])
            ),
            "source_sheet": "Сводная смета",
            "source_row": index + 1,
            "unit": row["unit"],
            "planned": float(row["quantity"]),
            "rate": float(row["rate"]),
            "baseline": 0,
        }
        for index, row in enumerate(rows)
    ]
    result = format_journal(content, positions, [], {}, [])
    book = openpyxl.load_workbook(io.BytesIO(result))
    for sheet in list(book):
        if not is_journal(sheet) and not any(
            cell.value is not None for row in sheet for cell in row
        ):
            book.remove(sheet)
    notes = book.create_sheet("Примечания PDF")
    notes.append(["Работа", "Категория", "Примечание", "Страницы PDF", "Упоминания"])
    by_id = {"pdf-" + row["id"]: row for row in rows}
    from openpyxl.comments import Comment

    for sheet in book:
        if not is_journal(sheet):
            continue
        for cell in sheet["A"]:
            metadata = journal_row(cell)
            if metadata and metadata[0] in by_id:
                row = by_id[metadata[0]]
                text = (
                    notes_with_sources(row)
                    + "\nСтраницы PDF: "
                    + ", ".join(str(source["page"]) for source in row["sources"])
                )
                sheet.cell(cell.row, 2).comment = Comment(text.strip(), "M100")
    for row in rows:
        notes.append(
            [
                row["name"],
                row["category"],
                notes_with_sources(row),
                ", ".join(str(source["page"]) for source in row["sources"]),
                row.get("mention_count", len(row["sources"])),
            ]
        )
    style_sheet(notes, 1, [55, 25, 85, 18, 14])
    sources = book.create_sheet("Источники PDF")
    sources.append(
        [
            "Работа",
            "Обозначение",
            "Страница PDF",
            "Исходный объём",
            "Ед.",
            "Исходное название",
            "Примечание",
            "Цитата",
            "Строка",
            "Раздел",
            "Подраздел",
        ]
    )
    for row in rows:
        for source in row.get("sources", []):
            sources.append(
                [
                    row["name"],
                    source.get("item_code", ""),
                    source["page"],
                    source.get("original_quantity"),
                    source.get("original_unit"),
                    source.get("name"),
                    source.get("notes"),
                    source["quote"],
                    source.get("source_row"),
                    source.get("section", ""),
                    source.get("subsection", ""),
                ]
            )
    style_sheet(sources, 1, [50, 22, 16, 18, 12, 55, 65, 100, 14, 30, 30])
    book.active = next(sheet for sheet in book if is_journal(sheet))
    output = io.BytesIO()
    book.save(output)
    from ..workbook_calculation import cache_formulas

    return cache_formulas(output.getvalue(), [], original=result)


class PreviewInput(BaseModel):
    version: str
    public_url: str = Field(min_length=10, max_length=2000)
    webhook_id: str = Field(min_length=1, max_length=100)
    object_name: str = Field(min_length=1, max_length=100)


class PublishInput(BaseModel):
    version: str
    token: str = Field(min_length=20, max_length=100)


@router.post("/{ident}/bitrix/reset")
async def reset_target(ident: str, request: Request):
    owner = request.state.user["telegram_id"]
    async with workspaces.mutation_lock("pdf:" + ident):
        with session() as database:
            job = owned(database, ident, owner)
            if job.status != "publish_retry":
                raise HTTPException(409, "Дождитесь проверки записи")
            target = dict(job.payload["publication"])
            rows = job.payload["groups"]
        webhook = job.payload.get("_publication_webhook") or profile_webhooks.webhook_url(
            owner, target["webhook_id"]
        )
        latest, _ = await bitrix.download_rest(webhook, target["file_id"])
        generated = make_workbook((folder(ident) / "publication-blank.xlsx").read_bytes(), rows)
        if bitrix.workbook_identity(latest) == bitrix.workbook_identity(generated):
            raise HTTPException(
                409, "Таблица уже записана. Нажмите «Проверить запись» для создания объекта."
            )
        with session() as database:
            job = owned(database, ident, owner)
            job.payload = {
                **job.payload,
                "publication_attempts": [*job.payload.get("publication_attempts", []), target],
                "publication": None,
            }
            job.status = "ready"
            job.updated_at = datetime.now(UTC)
            return public(job)


@router.post("/{ident}/bitrix/preview")
async def preview(ident: str, request: Request, body: PreviewInput):
    owner = request.state.user["telegram_id"]
    if not body.object_name.strip():
        raise HTTPException(422, "Укажите название объекта")
    with session() as database:
        job = owned(database, ident, owner)
        if job.status != "ready":
            raise HTTPException(409, "Сначала подтвердите все строки и расценки")
        if version(job.updated_at) != body.version:
            raise HTTPException(409, "Выборка обновилась. Повторите проверку файла.")
        rows = job.payload.get("groups", [])
        if not rows or financial_summary(rows)["priced"] != len(rows):
            raise HTTPException(409, "Подтвердите все строки")
    try:
        bitrix.validate_public(body.public_url)
        webhook = profile_webhooks.webhook_url(owner, body.webhook_id)
        file_id = await bitrix.resolve_public_file(body.public_url, webhook)
        content, meta = await bitrix.download_rest(webhook, file_id)
        if not meta["NAME"].lower().endswith(".xlsx"):
            raise ValueError("Для таблицы нужен пустой XLSX-файл")
        ensure_empty(content)
        with session() as database:
            job = database.scalar(
                select(DocumentJob)
                .where(DocumentJob.id == ident, DocumentJob.owner_id == owner)
                .with_for_update()
            )
            if job is None:
                raise HTTPException(404, "Документ удалён")
            if version(job.updated_at) != body.version or job.status != "ready":
                raise HTTPException(409, "Выборка обновилась. Повторите проверку файла.")
            target = {
                "token": secrets.token_urlsafe(24),
                "file_id": file_id,
                "name": meta["NAME"],
                "public_url": body.public_url,
                "webhook_id": body.webhook_id,
                "object_name": body.object_name.strip(),
                "source_hash": hashlib.sha256(content).hexdigest(),
                "rows_hash": row_hash(rows),
                "project_id": uuid4().hex,
                "phase": "preview",
                "checked_at": datetime.now(UTC).isoformat(),
            }
            (folder(ident) / "publication-blank.xlsx").write_bytes(content)
            job.payload = {**job.payload, "publication": target, "_publication_webhook": webhook}
            job.updated_at = datetime.now(UTC)
            return public(job)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            502, "Не удалось проверить файл Битрикс24. Повторите проверку."
        ) from error


def create_object(database, job, target, webhook, parsed):
    owner = job.owner_id
    database.scalar(select(User).where(User.telegram_id == owner).with_for_update())
    project = database.get(Project, target["project_id"])
    if project is not None:
        return project
    names = list(database.scalars(select(Project.name).where(Project.owner_id == owner)))
    name = unique_project_name(target["object_name"], names)
    path = (
        "project:" + target["project_id"]
        if postgres.enabled()
        else str(store.base_path().parent / "objects" / (target["project_id"] + ".sqlite3"))
    )
    project = Project(
        id=target["project_id"],
        owner_id=owner,
        name=name,
        db_path=path,
        created_at=datetime.now(UTC),
    )
    database.add(project)
    database.flush()
    settings = {
        "source": "bitrix",
        "source_name": target["name"],
        "public_url": target["public_url"],
        "webhook": webhook,
        "webhook_profile_id": target["webhook_id"],
        "file_id": str(target["file_id"]),
        "sheet_mappings": json.dumps(parsed["sheets"]),
        "last_import": datetime.now(UTC).isoformat(),
        "bitrix_read_status": "null",
        "bitrix_read_positions": "{}",
        "bitrix_read_days": "{}",
        "journal_status": "ready",
        "journal_note": "",
    }
    if postgres.enabled():
        database.execute(select(func.set_config("journal.project_id", project.id, True)))
        for row in parsed["positions"]:
            database.add(
                Position(
                    project_id=project.id,
                    **{
                        key: Decimal(str(row.get(key, 0)))
                        if key in {"planned", "rate", "baseline"}
                        else row.get(key)
                        for key in (
                            "id",
                            "name",
                            "section",
                            "unit",
                            "planned",
                            "rate",
                            "baseline",
                            "source_row",
                            "source_sheet",
                        )
                    },
                )
            )
        database.add_all(
            ProjectSetting(project_id=project.id, key=key, value=value)
            for key, value in settings.items()
        )
    else:
        store.init(path, seed=False)
        with store.connect(path) as local:
            for row in parsed["positions"]:
                store.insert_position(local, row)
            for key, value in settings.items():
                store.set_setting(local, key, value)
    return project


@router.post("/{ident}/bitrix/publish")
async def publish(ident: str, request: Request, body: PublishInput):
    owner = request.state.user["telegram_id"]
    async with workspaces.mutation_lock("pdf:" + ident):
        with session() as database:
            job = database.scalar(
                select(DocumentJob)
                .where(DocumentJob.id == ident, DocumentJob.owner_id == owner)
                .with_for_update()
            )
            if job is None:
                raise HTTPException(404, "Документ удалён")
            if job.status == "published":
                return public(job)
            if job.status == "publishing" and datetime.now(UTC) - job.updated_at.replace(
                tzinfo=UTC
            ) < timedelta(minutes=2):
                raise HTTPException(409, "Таблица ещё записывается")
            if (
                job.status not in {"ready", "publish_retry", "publishing"}
                or version(job.updated_at) != body.version
            ):
                raise HTTPException(409, "Обновите выборку перед записью")
            target = dict(job.payload.get("publication") or {})
            saved_webhook = job.payload.get("_publication_webhook")
            rows = job.payload.get("groups", [])
            if not secrets.compare_digest(str(target.get("token", "")), body.token) or target.get(
                "rows_hash"
            ) != row_hash(rows):
                raise HTTPException(409, "Повторно проверьте файл назначения")
            job.status = "publishing"
            job.updated_at = datetime.now(UTC)
        try:
            webhook = saved_webhook or profile_webhooks.webhook_url(owner, target["webhook_id"])
            original = (folder(ident) / "publication-blank.xlsx").read_bytes()
            generated = make_workbook(original, rows)
            latest, meta = await bitrix.download_rest(webhook, target["file_id"])
            expected = bitrix.workbook_identity(generated)
            if bitrix.workbook_identity(latest) != expected:
                if hashlib.sha256(latest).hexdigest() != target["source_hash"]:
                    raise ValueError(
                        "Файл изменился после проверки. Для записи выберите новый пустой файл."
                    )
                ensure_empty(latest)
                result = await bitrix.rest(
                    webhook,
                    "disk.file.uploadVersion",
                    {
                        "id": target["file_id"],
                        "fileContent": [meta["NAME"], base64.b64encode(generated).decode()],
                    },
                )
                if not result:
                    raise ValueError("Битрикс24 не подтвердил загрузку")
            verified, _ = await bitrix.download_rest(webhook, target["file_id"])
            if bitrix.workbook_identity(verified) != expected:
                raise ValueError("Битрикс24 ещё не подтвердил данные. Нажмите «Проверить запись».")
            mappings, _ = tables.discover(verified)
            parsed = bitrix.read_workbook(verified, mappings)
            with session() as database:
                job = database.scalar(
                    select(DocumentJob).where(DocumentJob.id == ident).with_for_update()
                )
                project = create_object(database, job, target, webhook, parsed)
                job.payload = {
                    **{
                        key: value
                        for key, value in job.payload.items()
                        if key != "_publication_webhook"
                    },
                    "publication": {
                        **target,
                        "phase": "published",
                        "object_name": project.name,
                        "published_at": datetime.now(UTC).isoformat(),
                    },
                }
                job.status = "published"
                job.updated_at = datetime.now(UTC)
                return public(job)
        except (ValueError, OSError, httpx.HTTPError, SQLAlchemyError, HTTPException) as error:
            with session() as database:
                job = database.get(DocumentJob, ident)
                job.status = "publish_retry"
                job.payload = {
                    **job.payload,
                    "publication": {**target, "phase": "retry"},
                    "notice": str(error)
                    if isinstance(error, ValueError)
                    else "Не удалось подтвердить запись. Проверьте её повторно — заполненный файл не будет перезаписан.",
                }
                job.updated_at = datetime.now(UTC)
            raise HTTPException(
                409, "Не удалось подтвердить запись. Нажмите «Проверить запись»."
            ) from error
