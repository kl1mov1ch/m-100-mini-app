import hashlib
import json
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import (
    bitrix,
    bitrix_disk,
    bitrix_review,
    profile_webhooks,
    store,
    tables,
    workbook_revision,
    workspaces,
)
from ..bitrix_refresh import entries_by_day, freshness, refresh_project, review_issues
from ..clock import now
from ..report_conflicts import ConflictResolution, conflict_state, resolve
from ..reporting import ai_settings, get_report, safe_config
from ..schemas import Connection
from ..synchronization import send_cumulative_report, table_lock, write_journal
from .objects import owned_object

router = APIRouter()


class DiskBookRequest(BaseModel):
    work_type: str = Field(default="Основные работы", min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    webhook_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DiskReportTarget(BaseModel):
    webhook_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


@router.post("/api/bitrix/disk-book")
async def create_disk_book(request: Request, body: DiskBookRequest):
    project = owned_object(request)
    webhook = profile_webhooks.webhook_url(project["owner_id"], body.webhook_id)
    try:
        folder_name = bitrix_disk.book_name(body.name)[:-5]
        work_type = bitrix_disk.book_name(body.work_type)[:-5]
        filename = "Отчётность проекта.xlsx"
        async with table_lock(project):
            with store.connect() as db:
                previous = bitrix_disk.saved_template(db) or {}
                if store.setting(db, "source") == "bitrix":
                    if (
                        previous.get("folder_name"),
                        previous.get("work_type"),
                        previous.get("webhook_id"),
                        str(previous.get("id")),
                    ) == (folder_name, work_type, body.webhook_id, store.setting(db, "file_id")):
                        return previous
                    raise HTTPException(409, "К объекту уже подключена рабочая таблица")
                if store.setting(db, "pending_import_token"):
                    raise HTTPException(409, "Сначала завершите проверку загруженной сметы.")
                snapshot = bitrix_disk.project_snapshot(db, project)
            content = await run_in_threadpool(bitrix_disk.project_workbook, project["id"], snapshot)
            storage = await bitrix_disk.personal_storage(webhook)
            root = await bitrix_disk.ensure_folder(webhook, storage, "storage", folder_name)
            folder = await bitrix_disk.ensure_folder(webhook, root, "folder", work_type)
            item = await bitrix_disk.find_child(webhook, folder, filename, "folder")
            if item and str(item.get("TYPE", "")).lower() == "folder":
                raise HTTPException(409, "Имя файла отчётности уже занято папкой.")
            if item is None:
                item = await bitrix_disk.upload_new(webhook, folder, filename, content)
            ident = int(item["ID"])
            verified, meta = await bitrix.download_rest(webhook, ident)
            if not bitrix_disk.workbook_belongs_to(verified, project["id"]):
                raise HTTPException(
                    409,
                    "В этой папке уже есть другая отчётность. Укажите другое название папки или вида работ.",
                )
            if await run_in_threadpool(workbook_revision.changes, content, verified):
                raise HTTPException(
                    409,
                    "Содержимое книги на Диске отличается от проекта. Существующий файл сохранён. Подключите его по ссылке для сверки или выберите другую папку.",
                )
            parsed = await run_in_threadpool(bitrix.read_workbook, verified, generated_only=True)
            if parsed is None or {p["id"] for p in parsed["positions"]} != {
                p["id"] for p in snapshot["positions"]
            }:
                raise ValueError("Проверка рабочего журнала не подтвердила все позиции объекта")
            try:
                external = await bitrix.rest(webhook, "disk.file.getExternalLink", {"id": ident})
            except (ValueError, httpx.HTTPError):
                external = ""
            saved = {
                **bitrix_disk.public_file(meta, webhook),
                "webhook_id": body.webhook_id,
                "folder_name": folder_name,
                "work_type": work_type,
                "share_url": bitrix_disk.share_link(external, webhook),
            }
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if store.setting(db, "source") == "bitrix":
                    raise HTTPException(409, "Подключение объекта изменилось. Обновите страницу.")
                if snapshot != bitrix_disk.project_snapshot(db, project) or store.setting(
                    db, "pending_import_token"
                ):
                    raise HTTPException(
                        409,
                        "Данные объекта изменились во время создания. Рабочая книга не подключена. Проверьте изменения в объекте.",
                    )
                values = {
                    bitrix_disk.TEMPLATE_KEY: json.dumps(saved, ensure_ascii=False),
                    "source": "bitrix",
                    "source_name": filename,
                    "file_id": str(ident),
                    "webhook": webhook,
                    "webhook_profile_id": body.webhook_id,
                    "public_url": "",
                    "table_detail_url": saved["url"],
                    "last_import": now(),
                    "journal_status": "ready",
                    "journal_note": "",
                    "journal_retry_at": "",
                    "journal_rebuild": "",
                    "bitrix_working_seen": "1",
                    "bitrix_read_issues": "[]",
                    "bitrix_read_status": "null",
                    "bitrix_read_positions": "{}",
                    "bitrix_read_days": "{}",
                    "bitrix_appearance": "null",
                    "bitrix_appearance_observed": "null",
                    "connection_check": "null",
                    "remote_days": json.dumps(entries_by_day(parsed["entries"])),
                }
                for key, value in values.items():
                    store.set_setting(db, key, value)
                db.execute(
                    "UPDATE reports SET sync_status='synced',sync_error='',sync_attempts=0,retry_at=''"
                )
            return saved
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except (httpx.HTTPError, KeyError, TypeError) as error:
        raise HTTPException(
            502, "Диск не подтвердил сохранение книги. Повторите с тем же названием."
        ) from error


class ShareLink(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post("/api/bitrix/disk-book/share-link")
async def save_share_link(request: Request, body: ShareLink):
    project = owned_object(request)
    async with table_lock(project):
        with store.connect() as db:
            book = bitrix_disk.saved_template(db) or {}
            webhook = store.setting(db, "webhook")
            ident = int(store.setting(db, "file_id", "0"))
            if store.setting(db, "source") != "bitrix" or not webhook or book.get("id") != ident:
                raise HTTPException(409, "Сначала подключите рабочую книгу")
        try:
            url = bitrix_disk.share_link(body.url.strip(), webhook)
            if not url:
                raise ValueError("Ссылка ведёт на другой портал")
            if urlparse(url).hostname == urlparse(webhook).hostname:
                expected = await bitrix.rest(webhook, "disk.file.getExternalLink", {"id": ident})
                if url != expected:
                    raise ValueError("Ссылка ведёт к другому файлу")
            else:
                content, public = await bitrix.fetch_public(bitrix.validate_public(url))
                public_id = public.get("file_id")
                if public_id and int(public_id) != ident:
                    raise ValueError("Ссылка ведёт к другому файлу")
                if not public_id:
                    remote, _ = await bitrix.download_rest(webhook, ident)
                    if not bitrix_disk.workbook_belongs_to(content, project["id"]) or (
                        await run_in_threadpool(workbook_revision.changes, remote, content)
                    ):
                        raise ValueError("Не удалось подтвердить книгу объекта")
        except (ValueError, httpx.HTTPError) as error:
            raise HTTPException(
                422,
                "Проверьте публичную ссылку на Excel: портал и файл должны совпадать с подключённой книгой.",
            ) from error
        with store.connect() as db:
            book["share_url"] = url
            store.set_setting(db, bitrix_disk.TEMPLATE_KEY, json.dumps(book, ensure_ascii=False))
        return book


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


def notice_setting(user):
    return f"table_notice_dismissed:{user['role']}:{user['telegram_id']}"


def notice_id(issue):
    identity = {key: value for key, value in issue.items() if key not in {"author", "retrying"}}
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def table_notice(db, project, user, names=None, *, include_dismissed=False):
    source = store.setting(db, "source")
    linked = source == "bitrix" and bool(
        store.setting(db, "public_url")
        or (store.setting(db, "webhook") and int(store.setting(db, "file_id", "0")))
    )
    status = freshness(db) if linked and store.setting(db, "bitrix_working_seen") == "1" else None
    issues = (
        [issue for issue in review_issues(db) or [] if issue["kind"] != "appearance"]
        if status and status["status"] == "review"
        else []
    )
    conflict = (
        conflict_state(db, issues)[0]
        if issues and user["role"] == "master" and user["telegram_id"] == project["owner_id"]
        else None
    )
    if status and status["status"] == "unavailable":
        issues.append({"kind": "connection", "title": "Битрикс24 не ответил"})
    if linked or source == "detached" or bitrix_disk.report_file_enabled(db):
        names = names or {}
        for row in db.execute(
            "SELECT date,author_id,sync_error,retry_at FROM reports "
            "WHERE sync_status='error' OR (sync_status='pending' AND sync_error<>'') "
            "ORDER BY date DESC"
        ):
            issues.append(
                {
                    "kind": "sync",
                    "title": "Отчёт не отправился в Битрикс24",
                    "date": row["date"],
                    "author": names.get(row["author_id"])
                    or row["author_id"]
                    or project["owner_name"],
                    "reason": row["sync_error"] or "Битрикс24 не подтвердил отправку.",
                    "retrying": bool(row["retry_at"]),
                }
            )
    issues = [{**issue, "id": notice_id(issue)} for issue in issues]
    if not include_dismissed:
        dismissed = set(json.loads(store.setting(db, notice_setting(user), "[]")))
        issues = [issue for issue in issues if issue["id"] not in dismissed]
    if issues:
        return {
            "project_id": project["id"],
            "project_name": project["name"],
            "can_check_table": linked,
            "issues": issues,
            "version": conflict["version"] if conflict else None,
        }
    return None


@router.get("/api/profile/table-notifications")
def table_notifications(request: Request):
    user = request.state.user
    with workspaces.registry() as db:
        names = {
            row["telegram_id"]: row["name"]
            for row in db.execute("SELECT telegram_id,name FROM users")
        }
    notices = []
    for project in workspaces.visible(user):
        with store.connect(project["db_path"]) as db:
            notice = table_notice(db, project, user, names)
        if notice:
            notices.append(notice)
    return notices


class DismissTableNotice(BaseModel):
    issue_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


@router.post("/api/profile/table-notifications/{project_id}/dismiss")
async def dismiss_table_notice(request: Request, project_id: str, body: DismissTableNotice):
    user = request.state.user
    project = workspaces.project(user, project_id)
    async with workspaces.mutation_lock(project_id):
        if not workspaces.exists(project_id):
            raise HTTPException(404, "Объект удалён")
        with store.connect(project["db_path"]) as db:
            db.execute("BEGIN IMMEDIATE")
            notice = table_notice(db, project, user, include_dismissed=True)
            active = {issue["id"] for issue in notice["issues"]} if notice else set()
            setting = notice_setting(user)
            dismissed = set(json.loads(store.setting(db, setting, "[]"))) & active
            dismissed.update(active if body.issue_id is None else active & {body.issue_id})
            store.set_setting(db, setting, json.dumps(sorted(dismissed)))
    return {"ok": True}


class TableNoticeRefresh(BaseModel):
    version: str | None = Field(default=None, max_length=64)


@router.post("/api/profile/table-notifications/{project_id}/refresh")
async def refresh_table_notice(request: Request, project_id: str, body: TableNoticeRefresh):
    user = request.state.user
    project = workspaces.project(user, project_id)
    if body.version and (user["role"] != "master" or user["telegram_id"] != project["owner_id"]):
        raise HTTPException(403, "Применить данные может мастер объекта.")
    async with workspaces.mutation_lock(project_id):
        if not workspaces.exists(project_id):
            raise HTTPException(404, "Объект удалён")
        checked = await refresh_project(project, max_age=0)
        if not checked or checked["status"] == "unavailable":
            raise HTTPException(409, "Таблица недоступна. Попробуйте обновить позже.")
        if body.version and checked["status"] == "review":
            await resolve(project, user, ConflictResolution(direction="app", version=body.version))
            verified = await refresh_project(project, max_age=0)
            if not verified or verified["status"] == "unavailable":
                raise HTTPException(409, "Данные загружены. Повторная проверка таблицы недоступна.")
        with store.connect(project["db_path"]) as db:
            return table_notice(db, project, user)


@router.post("/api/bitrix/consult")
async def consult(request: Request, explain: bool = False):
    project = owned_object(request)
    with store.connect() as database:
        status = freshness(database)
        issues = review_issues(database)
        working_seen = store.setting(database, "bitrix_working_seen") == "1"
    if not status or (status["status"] == "review" and (issues is None or not working_seen)):
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
        working_seen = store.setting(database, "bitrix_working_seen") == "1"
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
        parsed = bitrix.read_workbook(content, mappings, generated_only=True)
        has_journal = parsed is not None
        if not has_journal and not working_seen:
            discovered, warnings = tables.discover(content, original=True)
            if discovered:
                parsed = tables.extract(content, discovered)
                parsed["warnings"] = warnings + parsed["warnings"]
        parsed = parsed or {"warnings": [], "positions": [], "sheets": []}
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
            "message": (
                "В исходной таблице есть замечания к импорту."
                if not has_journal and problems
                else "Таблица доступна. Рабочий журнал ещё не создан."
                if not has_journal
                else "Рабочий журнал доступен"
                if not problems
                else "В рабочем журнале есть замечания"
            ),
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
