import csv
import io
import json
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import matcher, store, workspaces
from ..bitrix_refresh import remote_positions
from ..clock import now, today
from ..report_downloads import report_export
from ..report_snapshots import remember_start, restore_target
from ..reporting import ai_settings, get_report, history, report_changes, safe_config
from ..schemas import ParseBody, SaveBody
from ..synchronization import send_day

router = APIRouter()


@router.get("/api/bootstrap")
def bootstrap(request: Request):
    with store.connect() as db:
        hidden = store.hidden_positions(db)
        bitrix = remote_positions(db)
        master = request.state.user["role"] == "master"
        rows = history(db)
        current = get_report(db, today())
        if not master:
            for row in [*rows, current]:
                row["sync_error"] = ""
        return {
            "positions": [
                {
                    **position,
                    "hidden": position["id"] in hidden,
                    "bitrix": bitrix.get(position["id"]),
                }
                for position in store.positions(db)
            ],
            "history": rows,
            "config": safe_config(db, include_table_review=master),
            "report": current,
            "project": workspaces.public_project(request.state.project),
        }


@router.get("/api/report/{day}")
def report(day: date, request: Request):
    with store.connect() as db:
        result = get_report(db, day.isoformat())
    if request.state.user["role"] == "admin":
        result["sync_error"] = ""
    return result


@router.get("/api/changes")
def changes(request: Request):
    master = request.state.user["role"] == "master"
    with store.connect() as db:
        events = []
        for row in db.execute("SELECT * FROM audit ORDER BY id DESC"):
            payload = json.loads(row["payload"])
            if not master:
                if "changes" not in payload:
                    continue
                if "before" in payload:
                    payload["before"].pop("sync_error", None)
            events.append({**dict(row), "payload": payload})
            if len(events) == 100:
                break
        return events


@router.post("/api/parse")
async def parse(body: ParseBody):
    with store.connect() as db:
        ps = store.selectable_positions(db)
        settings = ai_settings(db)
    return await matcher.parse(body.text, ps, settings, body.local_only)


@router.post("/api/search")
async def search(body: ParseBody):
    with store.connect() as db:
        ps = store.selectable_positions(db)
        settings = ai_settings(db)
    return await matcher.search(body.text, ps, settings, body.local_only)


class RestoreBody(BaseModel):
    revision: int = Field(ge=1)


@router.post("/api/reports")
async def save(request: Request, body: SaveBody):
    return await persist_report(request, body)


@router.get("/api/report/{day}/restore-preview")
def restore_preview(day: date):
    with store.connect() as database:
        current = get_report(database, day.isoformat())
        return {"current": current, "target": restore_target(database, day.isoformat())}


@router.post("/api/report/{day}/restore")
async def restore(request: Request, day: date, body: RestoreBody):
    with store.connect() as database:
        target = restore_target(database, day.isoformat())
    return await persist_report(
        request,
        SaveBody(
            date=day,
            revision=body.revision,
            lines=target["lines"],
            crew_count=target["crew_count"],
            text=target.get("text") or "",
            allow_exceed=True,
        ),
        action="restore_day",
    )


async def persist_report(request: Request, body: SaveBody, action="edit_report"):
    day = body.date.isoformat()
    if day > today():
        raise HTTPException(422, "Дата выполнения не может быть в будущем")
    if len({l.item_id for l in body.lines}) != len(body.lines):
        raise HTTPException(422, "Объедините повторяющиеся позиции")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = get_report(db, day)
        if before["revision"] != body.revision:
            raise HTTPException(409, "Отчёт изменился в другом окне. Откройте его заново.")
        if not body.lines and not before["revision"] and not before["lines"]:
            raise HTTPException(422, "Добавьте выполненную работу перед подтверждением")
        ps = {p["id"]: p for p in store.positions(db)}
        old = {l["item_id"]: l["quantity"] for l in before["lines"]}
        hidden = store.hidden_positions(db)
        for line in body.lines:
            if line.item_id not in ps:
                raise HTTPException(422, "Позиция отсутствует в справочнике")
            if line.item_id in hidden and line.item_id not in old and action != "restore_day":
                raise HTTPException(409, "Работа скрыта из сметы. Обновите список работ.")
            if (
                line.quantity > ps[line.item_id]["remaining"] + old.get(line.item_id, 0) + 1e-8
                and not body.allow_exceed
            ):
                raise HTTPException(
                    422, "Объём превышает остаток. Подтвердите фактическое выполнение."
                )
        delta = report_changes(before, body, ps)
        changed = (
            bool(delta["lines"])
            or before["crew_count"] != body.crew_count
            or before["revision"] == 0
            or before["text"] != body.text
        )
        if not changed:
            return {**before, "changed": False, "changes": delta}
        remember_start(db, before)
        event = {
            "action": action,
            "before": before,
            "changes": delta,
            "actor_id": request.state.user["telegram_id"],
            "actor_name": request.state.user["name"],
        }
        db.execute(
            "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
            (day, json.dumps(event, ensure_ascii=False), now()),
        )
        db.execute("DELETE FROM entries WHERE date=?", (day,))
        db.executemany(
            "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
            [(l.item_id, day, l.quantity) for l in body.lines],
        )
        db.execute(
            """INSERT INTO reports(date,revision,text,updated_at,sync_status,crew_count,author_id,sync_error) VALUES(?,?,?,?,?,?,?,?)
          ON CONFLICT(date) DO UPDATE SET revision=excluded.revision,text=excluded.text,updated_at=excluded.updated_at,sync_status=excluded.sync_status,crew_count=excluded.crew_count,author_id=excluded.author_id,sync_error='' """,
            (
                day,
                body.revision + 1,
                body.text,
                now(),
                "pending",
                body.crew_count,
                request.state.user["telegram_id"],
                "",
            ),
        )
    await send_day(request.state.project, day)
    with store.connect() as db:
        return {**get_report(db, day), "changed": True, "changes": delta}


def render_csv(database_path):
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "Дата",
            "Работа",
            "Ед. изм.",
            "Объём",
            "Расценка BYN",
            "Сумма BYN",
            "Работников",
        ]
    )
    with store.connect(database_path) as db:
        for r in db.execute(
            "SELECT e.date,p.name,p.unit,e.quantity,p.rate,round(e.quantity*p.rate,2),r.crew_count FROM entries e JOIN positions p ON p.id=e.item_id LEFT JOIN reports r ON r.date=e.date ORDER BY e.date DESC,p.source_row"
        ):
            writer.writerow(
                [
                    "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                    for v in r
                ]
            )
    return ("\ufeff" + out.getvalue()).encode("utf-8")


@router.get("/api/export.csv")
def export(request: Request, prepare: bool = False):
    project_id = request.state.project["id"]

    def render(user):
        return render_csv(workspaces.project(user, project_id)["db_path"])

    return report_export(request.state.user, "reports.csv", "text/csv", render, prepare)


@router.post("/api/bitrix/sync/{day}")
async def sync(request: Request, day: date):
    with store.connect() as db:
        if not get_report(db, day.isoformat())["revision"]:
            raise HTTPException(400, "Сначала подтвердите отчёт")
    return await send_day(request.state.project, day.isoformat())
