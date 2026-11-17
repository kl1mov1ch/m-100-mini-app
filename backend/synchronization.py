import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from . import bitrix, bitrix_disk, profile_webhooks, store, workspaces
from .analytics_workbook import export_workbook
from .clock import now
from .reporting import ai_settings, get_report, history
from .table_advice import explain_issues

SYNC_LOCKS = {}
JOURNAL_PENDING_NOTE = "Таблица подтверждена. Лист «Журнал работ» ещё не записан в Битрикс24."


def render_cumulative_report(project):
    with store.connect(project["db_path"]) as db:
        rows = [
            {**row, "project_id": project["id"], "project_name": project["name"]}
            for row in history(db)
        ]
    user = {"role": "master", "telegram_id": project["owner_id"]}
    return export_workbook(user, {"rows": rows, "project_ids": [project["id"]]}, with_charts=False)


async def send_cumulative_report(project, report, target):
    status, detail, retry_at = "synced", "", ""
    try:
        webhook = profile_webhooks.webhook_url(project["owner_id"], target)
        content = await asyncio.to_thread(render_cumulative_report, project)
        await bitrix_disk.sync_report_file(webhook, project, target, content)
    except httpx.TransportError:
        status, detail = "pending", "Диск не ответил. Отчёт сохранён в приложении."
    except httpx.HTTPStatusError as error:
        status = (
            "pending"
            if error.response.status_code == 429 or error.response.status_code >= 500
            else "error"
        )
        detail = "Битрикс24 не принял отчёт. Проверьте доступ или повторите отправку."
    except HTTPException:
        status, detail = "error", "Вебхук отчётов удалён. Выберите действующий вебхук."
    except ValueError as error:
        status, detail = "error", str(error)
    except (KeyError, TypeError):
        status, detail = "error", "Не удалось подтвердить сохранение отчёта на Диске."
    attempts = report.get("sync_attempts", 0) + 1 if status != "synced" else 0
    if status == "pending":
        retry_at = (
            datetime.fromisoformat(now()) + timedelta(seconds=min(300, 5 * 2 ** min(attempts, 6)))
        ).isoformat()
    with store.connect(project["db_path"]) as db:
        db.execute(
            "UPDATE reports SET sync_status=?,sync_error=?,sync_attempts=?,retry_at=? WHERE date=? AND revision=?",
            (status, detail, attempts, retry_at, report["date"], report["revision"]),
        )
    return {"ok": status == "synced", "status": status, "message": detail}


def table_lock(project):
    with store.connect(project["db_path"]) as database:
        webhook = store.setting(database, "webhook")
        public_url = store.setting(database, "public_url")
        file_id = store.setting(database, "file_id")
    portal = urlparse(webhook).hostname
    if not portal and public_url:
        portal = urlparse(public_url).path.strip("/").split("/")[0]
    key = f"{portal}:{file_id}" if portal and file_id else project["id"]
    return SYNC_LOCKS.setdefault(key, asyncio.Lock())


async def write_journal(project):
    async with table_lock(project):
        rebuild = None
        with store.connect(project["db_path"]) as db:
            if store.setting(db, "source") != "bitrix":
                return {"status": "local", "message": "Таблица сохранена в приложении."}
            webhook = store.setting(db, "webhook")
            file_id = int(store.setting(db, "file_id", "0"))
            if not webhook or not file_id:
                message = "Таблица доступна для чтения. Для записи нужен вебхук с правом «Диск»."
                store.set_setting(db, "journal_status", "read_only")
                store.set_setting(db, "journal_note", message)
                return {"status": "read_only", "message": message}
            mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
            crew = {
                row["date"]: row["crew_count"]
                for row in db.execute(
                    "SELECT date,crew_count FROM reports WHERE sync_status='synced'"
                )
            }
            if store.setting(db, "journal_rebuild"):
                original = Path(store.setting(db, "import_file_path"))
                if not original.is_file():
                    return {"status": "pending", "message": "Повторно проверьте исходный файл."}
                rebuild = {
                    "original": original.read_bytes(),
                    "positions": store.positions(db),
                    "entries": [
                        dict(row) for row in db.execute("SELECT item_id,date,quantity FROM entries")
                    ],
                }
                crew.update(
                    {
                        row["date"]: row["crew_count"]
                        for row in db.execute("SELECT date,crew_count FROM reports")
                    }
                )
        status, note = "ready", ""
        try:
            if rebuild:
                await bitrix.upload_journal(webhook, file_id, mappings, crew, rebuild=rebuild)
            else:
                await bitrix.upload_journal(webhook, file_id, mappings, crew)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Bitrix journal write failed: %s", type(error).__name__
            )
            status, note = "pending", JOURNAL_PENDING_NOTE
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (
                401,
                403,
            ):
                note += " Проверьте права вебхука на изменение файла."
            elif isinstance(error, httpx.TransportError):
                note += " Битрикс24 не ответил. Повторите запись."
            elif isinstance(error, ValueError):
                note = str(error)
        with store.connect(project["db_path"]) as db:
            store.set_setting(db, "journal_status", status)
            store.set_setting(db, "journal_note", note)
            store.set_setting(
                db,
                "journal_retry_at",
                (datetime.fromisoformat(now()) + timedelta(minutes=2)).isoformat()
                if status == "pending"
                else "",
            )
            if status == "ready":
                store.set_setting(db, "journal_rebuild", "")
        return {"status": status, "message": note or "Лист «Журнал работ» проверен в Битрикс24."}


async def send_day(project, day):
    async with table_lock(project):
        if not workspaces.exists(project["id"]):
            return {"ok": False, "status": "local", "message": "Объект удалён"}
        with store.connect(project["db_path"]) as db:
            r = get_report(db, day)
            webhook = store.setting(db, "webhook")
            source = store.setting(db, "source")
            file_id = int(store.setting(db, "file_id", "0"))
            standalone = (
                store.setting(db, bitrix_disk.REPORT_TARGET_KEY)
                if bitrix_disk.report_file_enabled(db)
                else ""
            )
            ps = store.positions(db)
            if not standalone and (not webhook or source != "bitrix" or not file_id):
                msg = "Подключите таблицу Битрикс24 для автоматической отправки"
                db.execute(
                    "UPDATE reports SET sync_status='pending',sync_error=? WHERE date=?",
                    (msg, day),
                )
                return {"ok": False, "status": "pending", "message": msg}
            if r["sync_status"] == "synced":
                return {"ok": True, "status": "synced"}
            if store.setting(db, "journal_rebuild"):
                return {
                    "ok": False,
                    "status": "pending",
                    "message": "Рабочие листы обновляются. Отчёт сохранён.",
                }
            baseline = json.loads(store.setting(db, "remote_days", "{}")).get(day, {})
            mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
            crew = {
                row["date"]: row["crew_count"]
                for row in db.execute(
                    "SELECT date,crew_count FROM reports WHERE sync_status='synced'"
                )
            }
            settings = ai_settings(db)
        if standalone:
            return await send_cumulative_report(project, r, standalone)
        try:
            result = await bitrix.upload_day(
                webhook, file_id, day, r["lines"], ps, r["payroll"], baseline, mappings, crew
            )
            issues = (result or {}).get("issues", [])
            tips = await explain_issues(issues, settings)
            note = ""
            if issues:
                first = issues[0]
                note = first["message"] + (f" {tips[first['id']]}" if first["id"] in tips else "")
            with store.connect(project["db_path"]) as db:
                if get_report(db, day)["revision"] == r["revision"]:
                    db.execute(
                        "UPDATE reports SET sync_status='synced',sync_error=?,retry_at='',sync_attempts=0 WHERE date=?",
                        (note, day),
                    )
                baselines = json.loads(store.setting(db, "remote_days", "{}"))
                baselines[day] = {l["item_id"]: l["quantity"] for l in r["lines"]}
                store.set_setting(db, "remote_days", json.dumps(baselines))
                store.set_setting(db, "journal_status", "ready")
                store.set_setting(db, "journal_note", "")
            return {"ok": True, "status": "synced"}
        except (ValueError, httpx.HTTPError, KeyError, TypeError) as e:
            transient = (
                isinstance(e, httpx.TransportError)
                or isinstance(e, httpx.HTTPStatusError)
                and (e.response.status_code == 429 or e.response.status_code >= 500)
            )
            status = "pending" if transient else "error"
            msg = (
                str(e)
                if isinstance(e, ValueError)
                else "Битрикс24 недоступен. Изменения сохранены, повторите отправку."
            )
            if isinstance(e, ValueError):
                tip = await explain_issues([{"id": "sync", "message": msg}], settings)
                if tip.get("sync"):
                    msg += " " + tip["sync"]
            with store.connect(project["db_path"]) as db:
                if get_report(db, day)["revision"] == r["revision"]:
                    attempt = r.get("sync_attempts", 0) + 1
                    retry_at = (
                        (
                            datetime.fromisoformat(now())
                            + timedelta(seconds=min(300, 5 * 2 ** min(attempt, 6)))
                        ).isoformat()
                        if transient
                        else ""
                    )
                    db.execute(
                        "UPDATE reports SET sync_status=?,sync_error=?,sync_attempts=?,retry_at=? WHERE date=?",
                        (status, msg, attempt, retry_at, day),
                    )
            return {"ok": False, "status": status, "message": msg}


async def retry_pending_reports():
    while True:
        await asyncio.sleep(15)
        with workspaces.registry() as registry:
            projects = [
                dict(row)
                for row in registry.execute(
                    "SELECT p.* FROM projects p JOIN users u ON u.telegram_id=p.owner_id WHERE u.enabled=1"
                )
            ]
        for project in projects:
            with store.connect(project["db_path"]) as database:
                sheet_mode = (
                    bool(store.setting(database, "webhook"))
                    and store.setting(database, "source") == "bitrix"
                    and store.setting(database, "file_id", "0") != "0"
                )
                standalone = bitrix_disk.report_file_enabled(database)
                if not sheet_mode and not standalone:
                    continue
                since = store.setting(database, "bitrix_report_files_since") if standalone else ""
                dates = [
                    row["date"]
                    for row in database.execute(
                        "SELECT date FROM reports WHERE sync_status='pending' AND (retry_at='' OR retry_at<=?) "
                        "AND updated_at>=? ORDER BY date",
                        (now(), since or "0001-01-01"),
                    )
                ]
                pending_journal = (
                    sheet_mode
                    and store.setting(database, "journal_status") == "pending"
                    and store.setting(database, "journal_retry_at") <= now()
                )
            if pending_journal:
                try:
                    await write_journal(project)
                except Exception:
                    continue
            for report_date in dates:
                try:
                    await send_day(project, report_date)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
