import asyncio
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from . import bitrix, store, workspaces
from .clock import now
from .reporting import get_report

SYNC_LOCKS = {}


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


async def send_day(project, day):
    async with table_lock(project):
        with store.connect(project["db_path"]) as db:
            r = get_report(db, day)
            webhook = store.setting(db, "webhook")
            source = store.setting(db, "source")
            file_id = int(store.setting(db, "file_id", "0"))
            ps = store.positions(db)
            if not webhook or source != "bitrix":
                msg = "Подключите таблицу Битрикс24 для автоматической отправки"
                db.execute(
                    "UPDATE reports SET sync_status='pending',sync_error=? WHERE date=?",
                    (msg, day),
                )
                return {"ok": False, "status": "pending", "message": msg}
            if r["sync_status"] == "synced":
                return {"ok": True, "status": "synced"}
            baseline = json.loads(store.setting(db, "remote_days", "{}")).get(day, {})
            mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
        try:
            await bitrix.upload_day(
                webhook, file_id, day, r["lines"], ps, r["payroll"], baseline, mappings
            )
            with store.connect(project["db_path"]) as db:
                if get_report(db, day)["revision"] == r["revision"]:
                    db.execute(
                        "UPDATE reports SET sync_status='synced',sync_error='',retry_at='',sync_attempts=0 WHERE date=?",
                        (day,),
                    )
                baselines = json.loads(store.setting(db, "remote_days", "{}"))
                baselines[day] = {l["item_id"]: l["quantity"] for l in r["lines"]}
                store.set_setting(db, "remote_days", json.dumps(baselines))
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
                if (
                    not store.setting(database, "webhook")
                    or store.setting(database, "source") != "bitrix"
                ):
                    continue
                dates = [
                    row["date"]
                    for row in database.execute(
                        "SELECT date FROM reports WHERE sync_status='pending' AND (retry_at='' OR retry_at<=?) ORDER BY date",
                        (now(),),
                    )
                ]
            for report_date in dates:
                try:
                    await send_day(project, report_date)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
