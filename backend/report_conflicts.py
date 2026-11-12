import hashlib
import json
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from . import bitrix, store
from .bitrix_refresh import freshness, review_issues
from .clock import now
from .report_snapshots import remember_start
from .reporting import get_report
from .synchronization import table_lock


class ConflictResolution(BaseModel):
    direction: Literal["app", "table"]
    version: str


def conflict_state(db, issues):
    changed = [item for item in issues if item["kind"] == "report"]
    days = sorted({item["date"] for item in changed})
    fields = {}
    for issue in issues:
        if issue["kind"] in ("planned", "rate") and issue.get("item_id"):
            fields.setdefault(issue["item_id"], {})[issue["kind"]] = issue["remote"]
    if not days and not fields:
        return None, {}, {}, {}
    reports = {day: get_report(db, day) for day in days}
    snapshot = json.loads(store.setting(db, "bitrix_read_days", "{}"))
    remote = {day: snapshot.get(day, {}) for day in days}
    local = {position["id"]: position for position in store.positions(db)} if fields else {}
    local_fields = {
        ident: {field: local[ident][field] for field in values}
        for ident, values in fields.items()
        if ident in local
    }
    version = hashlib.sha256(
        json.dumps([reports, remote, fields, local_fields], sort_keys=True).encode()
    ).hexdigest()
    return (
        {
            "version": version,
            "days": len(days),
            "positions": len(changed),
            "deleted": sum(item["remote"] == 0 for item in changed),
            "fields": sum(len(values) for values in fields.values()),
            "can_write": bool(
                store.setting(db, "webhook") and int(store.setting(db, "file_id", "0"))
            ),
        },
        reports,
        remote,
        fields,
    )


async def resolve(project, user, body):
    async with table_lock(project):
        path = project["db_path"]
        with store.connect(path) as db:
            status = freshness(db)
            if (
                store.setting(db, "source") != "bitrix"
                or not status
                or status["status"] != "review"
            ):
                raise HTTPException(409, "Обновите различия и попробуйте ещё раз.")
            summary, reports, expected, fields = conflict_state(db, review_issues(db) or [])
            if not summary or summary["version"] != body.version:
                raise HTTPException(409, "Данные изменились. Откройте различия заново.")
            webhook = store.setting(db, "webhook")
            file_id = int(store.setting(db, "file_id", "0"))
            url = store.setting(db, "public_url")
            mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
            catalogue = store.positions(db)
        try:
            if body.direction == "table":
                if not summary["can_write"]:
                    raise HTTPException(409, "Для записи нужен вебхук с правом «Диск».")
                await bitrix.upload_days(
                    webhook, file_id, reports, catalogue, mappings, None, expected, fields
                )
                resolved = {day: bitrix.line_values(report) for day, report in reports.items()}
                remote_crew = {}
            else:
                content, _ = await (
                    bitrix.download_rest(webhook, file_id)
                    if webhook and file_id
                    else bitrix.fetch_public(url)
                )
                parsed = bitrix.read_workbook(content, mappings)
                bitrix.verify_report_inputs(parsed, reports, catalogue, {}, fields)
                remote_fields = {position["id"]: position for position in parsed["positions"]}
                if any(
                    remote_fields[ident][field] != value
                    for ident, changes in fields.items()
                    for field, value in changes.items()
                ):
                    raise ValueError(
                        "Смета изменилась. Обновите различия и выберите вариант ещё раз."
                    )
                resolved = {day: bitrix.day_values(parsed, day) for day in reports}
                if any(
                    not bitrix.equal_quantities(expected[day], values)
                    for day, values in resolved.items()
                ):
                    raise ValueError(
                        "Таблица изменилась. Обновите различия и выберите вариант ещё раз."
                    )
                if any(
                    warning.get("date") in reports
                    or any(item["date"] in reports for item in warning.get("duplicates", []))
                    for warning in parsed.get("warnings", [])
                ):
                    raise ValueError("Сначала исправьте нечисловые объёмы или повторяющиеся даты.")
                remote_crew = parsed.get("crew_by_day", {})
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(409, str(error)) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                502, "Битрикс24 не подтвердил операцию. Обновите данные перед повтором."
            ) from error

        with store.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            baseline = json.loads(store.setting(db, "remote_days", "{}"))
            if fields and body.direction == "app":
                for ident, values in fields.items():
                    db.execute(
                        "UPDATE positions SET planned=COALESCE(?,planned),rate=COALESCE(?,rate) WHERE id=?",
                        (values.get("planned"), values.get("rate"), ident),
                    )
            if fields:
                previous = {position["id"]: position for position in catalogue}
                updates = {
                    ident: {
                        "before": {field: previous[ident][field] for field in values},
                        "after": values,
                    }
                    for ident, values in fields.items()
                }
                db.execute(
                    "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
                    (
                        now()[:10],
                        json.dumps(
                            {
                                "action": "bitrix_resolve",
                                "direction": body.direction,
                                "position_updates": updates,
                                "actor_name": user["name"],
                            },
                            ensure_ascii=False,
                        ),
                        now(),
                    ),
                )
            for day, before in reports.items():
                if body.direction == "app":
                    remember_start(db, before)
                    db.execute("DELETE FROM entries WHERE date=?", (day,))
                    db.executemany(
                        "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
                        [
                            (ident, day, quantity)
                            for ident, quantity in resolved[day].items()
                            if quantity
                        ],
                    )
                crew = remote_crew.get(day, before["crew_count"])
                db.execute(
                    "UPDATE reports SET revision=revision+1,updated_at=?,crew_count=?,sync_status='synced',sync_error='',retry_at='',sync_attempts=0 WHERE date=?",
                    (now(), crew, day),
                )
                db.execute(
                    "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
                    (
                        day,
                        json.dumps(
                            {
                                "action": "bitrix_resolve",
                                "direction": body.direction,
                                "before": before,
                                "actor_id": user["telegram_id"],
                                "actor_name": user["name"],
                            },
                            ensure_ascii=False,
                        ),
                        now(),
                    ),
                )
            baseline.update(resolved)
            store.set_setting(db, "remote_days", json.dumps(baseline))
            store.set_setting(db, "bitrix_read_status", "null")
            if body.direction == "table":
                store.set_setting(db, "journal_status", "ready")
                store.set_setting(db, "journal_note", "")
    return {"days": len(reports)}
