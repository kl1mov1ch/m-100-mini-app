import json
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import (
    bitrix,
    bitrix_disk,
    bitrix_review,
    profile_webhooks,
    store,
    tables,
    workbook_revision,
)
from ..bitrix_refresh import freshness, refresh_project, review_issues
from ..clock import now
from ..report_conflicts import ConflictResolution, conflict_state, resolve
from ..reporting import ai_settings, get_report, safe_config
from ..schemas import Connection
from ..synchronization import send_cumulative_report, table_lock, write_journal
from .objects import owned_object

router = APIRouter()


class DiskBookRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    webhook_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DiskReportTarget(BaseModel):
    webhook_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


@router.post("/api/bitrix/disk-book")
async def create_disk_book(request: Request, body: DiskBookRequest):
    project = owned_object(request)
    webhook = profile_webhooks.webhook_url(project["owner_id"], body.webhook_id)
    try:
        name = bitrix_disk.book_name(body.name)
        async with table_lock(project):
            with store.connect() as db:
                if store.setting(db, "source") == "bitrix":
                    raise HTTPException(409, "К объекту уже подключена рабочая таблица")
            folder = await bitrix_disk.object_folder(webhook, project)
            item = await bitrix_disk.find_child(webhook, folder, name, "folder")
            if item:
                content, _ = await bitrix.download_rest(webhook, int(item["ID"]))
                if not bitrix_disk.workbook_belongs_to(content, project["id"]):
                    raise HTTPException(409, "Файл с таким названием уже есть. Укажите другое имя.")
            else:
                item = await bitrix_disk.upload_new(
                    webhook, folder, name, bitrix_disk.starter_workbook(project["id"])
                )
            meta = await bitrix.rest(webhook, "disk.file.get", {"id": int(item["ID"])})
            saved = {**bitrix_disk.public_file(meta, webhook), "webhook_id": body.webhook_id}
            if saved["name"] != name:
                raise ValueError("Битрикс24 сохранил книгу с другим названием")
            with store.connect() as db:
                store.set_setting(
                    db, bitrix_disk.TEMPLATE_KEY, json.dumps(saved, ensure_ascii=False)
                )
            return saved
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except (httpx.HTTPError, KeyError, TypeError) as error:
        raise HTTPException(
            502, "Диск не подтвердил сохранение книги. Повторите с тем же названием."
        ) from error


@router.post("/api/bitrix/report-files")
async def configure_report_files(request: Request, body: DiskReportTarget):
    project = owned_object(request)
    if body.webhook_id:
        webhook = profile_webhooks.webhook_url(project["owner_id"], body.webhook_id)
        try:
            await bitrix_disk.personal_storage(webhook)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, "Проверьте доступ вебхука к Битрикс24.Диску") from error
    async with table_lock(project):
        with store.connect() as db:
            old = store.setting(db, bitrix_disk.REPORT_TARGET_KEY)
            if old != (body.webhook_id or ""):
                store.set_setting(db, bitrix_disk.REPORT_TARGET_KEY, body.webhook_id or "")
                store.set_setting(db, "bitrix_report_files_since", now() if body.webhook_id else "")
    return {"webhook_id": body.webhook_id}


@router.post("/api/bitrix/report-files/publish")
async def publish_report_files(request: Request):
    project = owned_object(request)
    async with table_lock(project):
        with store.connect() as db:
            if not bitrix_disk.report_file_enabled(db):
                raise HTTPException(409, "Подключите вебхук для отдельной книги отчётов")
            target = store.setting(db, bitrix_disk.REPORT_TARGET_KEY)
            latest = db.execute("SELECT date FROM reports ORDER BY date DESC LIMIT 1").fetchone()
            if not latest:
                raise HTTPException(409, "Сначала подтвердите дневной отчёт")
            report = get_report(db, str(latest["date"]))
        result = await send_cumulative_report(project, report, target)
        if not result["ok"]:
            raise HTTPException(409, result["message"])
        with store.connect() as db:
            return safe_config(db)["bitrix_report_file"]


@router.post("/api/bitrix/journal")
async def journal(request: Request):
    return await write_journal(owned_object(request))


@router.post("/api/bitrix/refresh")
async def refresh(request: Request, force: bool = False):
    return await refresh_project(request.state.project, max_age=15 if force else 90)


@router.post("/api/bitrix/consult")
async def consult(request: Request, explain: bool = False):
    project = owned_object(request)
    with store.connect() as database:
        status = freshness(database)
        issues = review_issues(database)
    if not status or (status["status"] == "review" and issues is None):
        await refresh_project(project, max_age=0)
    with store.connect() as database:
        status = freshness(database)
        if not status or status["status"] == "unavailable":
            raise HTTPException(409, "Битрикс24 не ответил. Обновите данные и попробуйте ещё раз.")
        issues = (review_issues(database) or []) if status["status"] == "review" else []
        settings = ai_settings(database) if explain else None
        conflicts = None if explain else conflict_state(database, issues)[0]
    if explain:
        return {"advice": await bitrix_review.advise(issues, settings)}
    return {"issues": [item for item in issues if item["kind"] != "report"], "conflicts": conflicts}


@router.post("/api/bitrix/reconcile")
async def reconcile(request: Request, body: ConflictResolution):
    return await resolve(owned_object(request), request.state.user, body)


@router.post("/api/bitrix/accept-appearance")
async def accept_appearance(request: Request, version: str):
    async with table_lock(owned_object(request)):
        with store.connect() as db:
            observed = json.loads(store.setting(db, "bitrix_appearance_observed", "null"))
            if (
                not isinstance(observed, dict)
                or workbook_revision.appearance_version(observed) != version
            ):
                raise HTTPException(409, "Оформление изменилось. Обновите проверку.")
            store.set_setting(db, "bitrix_appearance", json.dumps(observed, ensure_ascii=False))
            issues = [
                issue for issue in review_issues(db) or [] if issue.get("kind") != "appearance"
            ]
            store.set_setting(db, "bitrix_read_issues", json.dumps(issues, ensure_ascii=False))
            status = freshness(db)
            if status and status["status"] == "review" and not issues:
                store.set_setting(
                    db, "bitrix_read_status", json.dumps({**status, "status": "current"})
                )
    return {"ok": True}


@router.post("/api/bitrix/check")
async def check_connection():
    with store.connect() as database:
        webhook = store.setting(database, "webhook")
        public_url = store.setting(database, "public_url")
        file_id = int(store.setting(database, "file_id", "0"))
        mappings = json.loads(store.setting(database, "sheet_mappings", "null"))
    try:
        if not webhook and not public_url:
            raise ValueError("Сначала подключите таблицу Битрикс24")
        if webhook:
            content, metadata = await bitrix.download_rest(webhook, file_id)
            name = metadata["NAME"]
            detail_url = metadata.get("DETAIL_URL") or public_url
        else:
            content, metadata = await bitrix.fetch_public(public_url)
            name = metadata["name"]
            detail_url = public_url
        if not mappings:
            mappings, _ = tables.discover(content)
        parsed = bitrix.read_workbook(content, mappings)
        problems = [warning for warning in parsed["warnings"] if warning.get("severity") != "info"]
        result = {
            "reachable": True,
            "structure_valid": True,
            "checked_at": now(),
            "name": name,
            "positions": len(parsed["positions"]),
            "sheets": len(parsed.get("sheets", mappings)),
            "issues": problems,
            "write_configured": bool(webhook),
            "message": "Таблица отвечает"
            if not problems
            else "Таблица отвечает, есть замечания к данным",
        }
        with store.connect() as database:
            store.set_setting(database, "connection_check", json.dumps(result, ensure_ascii=False))
            if detail_url and urlparse(detail_url).scheme == "https":
                store.set_setting(database, "table_detail_url", detail_url)
        return result
    except (ValueError, httpx.HTTPError, KeyError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Битрикс24 не ответил. Проверьте ссылку и доступ к файлу."
        )
        result = {
            "reachable": False,
            "checked_at": now(),
            "issues": [],
            "message": message,
            "write_configured": bool(webhook),
        }
        with store.connect() as database:
            store.set_setting(database, "connection_check", json.dumps(result, ensure_ascii=False))
        return result


@router.post("/api/bitrix/connection")
async def connection(request: Request, body: Connection):
    try:
        with store.connect() as db:
            saved_webhook = store.setting(db, "webhook")
            saved_id = int(store.setting(db, "file_id", "0"))
            saved_url = store.setting(db, "public_url")
        if body.webhook_id:
            owned_object(request)
            webhook = profile_webhooks.webhook_url(
                request.state.user["telegram_id"], body.webhook_id
            )
        else:
            webhook = body.webhook.strip() or saved_webhook
        url = body.public_url.strip() or saved_url
        file_id = body.file_id or saved_id or None
        if url:
            file_id = await bitrix.resolve_public_file(url, webhook, file_id)
        elif webhook and file_id:
            await bitrix.download_rest(webhook, file_id)
        else:
            raise ValueError("Укажите публичную ссылку на таблицу Битрикс24")
        with store.connect() as db:
            if store.setting(db, "source") == "bitrix" and saved_id and saved_id != file_id:
                raise HTTPException(409, "Для другого файла добавьте отдельный объект")
            for k, v in [
                ("public_url", url),
                ("file_id", str(file_id or 0)),
            ]:
                store.set_setting(db, k, v)
            if body.webhook_id or body.webhook.strip():
                store.set_setting(db, "webhook", webhook)
                store.set_setting(db, "webhook_profile_id", body.webhook_id or "")
            return safe_config(db)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except (httpx.HTTPError, KeyError, TypeError):
        raise HTTPException(
            400, "Не удалось подключиться. Проверьте вебхук, ID файла и право «Диск»."
        )
