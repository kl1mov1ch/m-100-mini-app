import json
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import bitrix, reconciliation, store, tables
from .synchronization import table_lock


class ConfirmImport(BaseModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    sheets: list[dict]
    acknowledged: list[str] = []
    position_matches: dict[str, str | None] = Field(default_factory=dict)
    reconciliation_acknowledged: bool = False
    reconciliation_version: str = ""
    day_resolutions: dict[str, str] = Field(default_factory=dict)


def import_sheets(sheets):
    return [
        {key: value for key, value in sheet.items() if key != "position_ids"} for sheet in sheets
    ]


def current_reconciliation(data):
    with store.connect() as database:
        return reconciliation.build_plan(database, data["positions"], data.get("entries"))


def directory():
    p = store.base_path().parent / "imports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_pending(token, project):
    try:
        meta = json.loads((directory() / f"{token}.json").read_text(encoding="utf-8"))
        if meta["project_id"] != project:
            raise HTTPException(403, "Эта таблица принадлежит другому объекту")
        return meta, (directory() / f"{token}.xlsx").read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "Импорт не найден. Загрузите файл снова.")


def register(app, settings, now):
    async def prepare(request, content, name, source, remote=None):
        with store.connect() as db:
            cfg = settings(db)
        try:
            analysis = await tables.analyze(content, cfg)
        except ValueError as e:
            raise HTTPException(422, str(e))
        token = uuid.uuid4().hex
        meta = {
            "project_id": request.state.project["id"],
            "owner_id": request.state.user["telegram_id"],
            "name": name,
            "source": source,
            "remote": remote,
            "warnings": analysis["warnings"],
            "sheets": analysis["sheets"],
            "created_at": now(),
        }
        (directory() / f"{token}.xlsx").write_bytes(content)
        (directory() / f"{token}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        with store.connect() as db:
            store.set_setting(db, "pending_import_token", token)
        return {
            "token": token,
            "name": name,
            "source": source,
            **analysis,
            "reconciliation": current_reconciliation(analysis),
        }

    @app.get("/api/imports/pending")
    async def pending(request: Request):
        with store.connect() as db:
            token = store.setting(db, "pending_import_token")
        if not token:
            return None
        meta, content = read_pending(token, request.state.project["id"])
        data = tables.extract(content, meta["sheets"])
        structural = [
            warning
            for warning in meta["warnings"]
            if any(
                reason in warning["id"] for reason in ("ai-mapping", "ambiguous", "name-guessed")
            )
        ]
        return {
            "token": token,
            "name": meta["name"],
            "source": meta["source"],
            **data,
            "warnings": structural + data["warnings"],
            "reconciliation": current_reconciliation(data),
        }

    @app.post("/api/imports/upload")
    async def upload(request: Request):
        form = await request.form(max_files=1, max_part_size=16 * 1024 * 1024)
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(422, "Выберите файл Excel или CSV")
        filename = Path(file.filename or "table.xlsx").name
        if not filename.lower().endswith((".xlsx", ".csv")):
            raise HTTPException(422, "Поддерживаются .xlsx и .csv")
        content = await file.read(15 * 1024 * 1024 + 1)
        try:
            content = tables.load(content, filename)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return await prepare(request, content, filename, "file")

    @app.post("/api/imports/bitrix")
    async def remote(request: Request):
        with store.connect() as db:
            webhook = store.setting(db, "webhook")
            file_id = int(store.setting(db, "file_id", "0"))
            url = store.setting(db, "public_url", bitrix.PUBLIC_URL)
        try:
            if webhook:
                content, meta = await bitrix.download_rest(webhook, file_id)
                remote = {"name": meta["NAME"], "file_id": file_id}
            else:
                content, meta = await bitrix.fetch_public(url)
                remote = meta
            return await prepare(request, content, remote["name"], "bitrix", remote)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                502,
                "Битрикс не отдал Excel. Подключите входящий вебхук с правом «Диск» и проверьте ID файла.",
            )

    @app.post("/api/imports/review")
    async def review(request: Request, body: ConfirmImport):
        meta, content = read_pending(body.token, request.state.project["id"])
        try:
            data = tables.extract(content, import_sheets(body.sheets))
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        old = [
            w
            for w in meta["warnings"]
            if any(k in w["id"] for k in ("ai-mapping", "name-guessed", "ambiguous"))
        ]
        return {
            "token": body.token,
            "name": meta["name"],
            "source": meta["source"],
            **data,
            "warnings": old + data["warnings"],
            "reconciliation": current_reconciliation(data),
        }

    @app.post("/api/imports/resolve")
    async def resolve(request: Request, body: ConfirmImport):
        meta, content = read_pending(body.token, request.state.project["id"])
        data = tables.extract(content, import_sheets(body.sheets))
        with store.connect() as database:
            plan = reconciliation.build_plan(database, data["positions"], data["entries"])
            if plan:
                plan = await reconciliation.suggest_matches(
                    database, plan, data["positions"], settings(database)
                )
        return plan

    @app.post("/api/imports/confirm")
    async def confirm(request: Request, body: ConfirmImport):
        meta, content = read_pending(body.token, request.state.project["id"])
        try:
            data = tables.extract(content, import_sheets(body.sheets))
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        mandatory = {w["id"] for w in data["warnings"] if w.get("severity") != "info"} | {
            w["id"]
            for w in meta["warnings"]
            if any(k in w["id"] for k in ("ai-mapping", "name-guessed", "ambiguous"))
        }
        if not mandatory.issubset(body.acknowledged):
            raise HTTPException(
                422,
                "Проверьте и подтвердите жёлтые блоки. После изменения столбцов нажмите «Перепроверить».",
            )
        async with table_lock(request.state.project):
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                data = reconciliation.reconcile_import(
                    db,
                    data,
                    body.position_matches,
                    body.reconciliation_acknowledged,
                    body.reconciliation_version,
                    body.token,
                )
                report_dates = {row[0] for row in db.execute("SELECT date FROM reports")}
                from .reporting import get_report

                reports_before = {day: get_report(db, day) for day in sorted(report_dates)}
                preserved = [
                    dict(r)
                    for r in db.execute("SELECT e.* FROM entries e JOIN reports r ON r.date=e.date")
                ]
                dirty = report_dates
                remote_days = {}
                for e in data["entries"]:
                    remote = remote_days.setdefault(e["date"], {})
                    remote[e["item_id"]] = remote.get(e["item_id"], 0) + e["quantity"]
                db.execute("DELETE FROM entries")
                db.execute("DELETE FROM positions")
                for p in data["positions"]:
                    store.insert_position(db, p)
                for e in data["entries"]:
                    db.execute(
                        "INSERT INTO entries VALUES(:item_id,:date,:quantity) ON CONFLICT(item_id,date) DO UPDATE SET quantity=quantity+excluded.quantity",
                        e,
                    )
                for day in dirty:
                    db.execute("DELETE FROM entries WHERE date=?", (day,))
                for e in preserved:
                    db.execute("INSERT INTO entries VALUES(:item_id,:date,:quantity)", e)
                for report_day in sorted(report_dates):
                    resolution = body.day_resolutions.get(report_day, "report")
                    if resolution not in ("report", "table"):
                        raise HTTPException(
                            422, "Выберите, какие объёмы сохранить: из отчёта или из таблицы"
                        )
                    if resolution == "table":
                        db.execute("DELETE FROM entries WHERE date=?", (report_day,))
                        db.executemany(
                            "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
                            [
                                (ident, report_day, quantity)
                                for ident, quantity in remote_days.get(report_day, {}).items()
                            ],
                        )
                        db.execute(
                            "UPDATE reports SET revision=revision+1,sync_status='pending',sync_error='',retry_at='',sync_attempts=0 WHERE date=?",
                            (report_day,),
                        )
                        continue
                    local = {
                        entry["item_id"]: entry["quantity"]
                        for entry in preserved
                        if entry["date"] == report_day
                    }
                    if local != remote_days.get(report_day, {}) or body.reconciliation_acknowledged:
                        db.execute(
                            "UPDATE reports SET revision=revision+1,sync_status='pending',sync_error='',retry_at='',sync_attempts=0 WHERE date=?",
                            (report_day,),
                        )
                    else:
                        db.execute(
                            "UPDATE reports SET revision=revision+1 WHERE date=?", (report_day,)
                        )
                db.execute(
                    "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
                    (
                        now()[:10],
                        json.dumps(
                            {
                                "action": "catalogue_reconciled",
                                "actor_id": request.state.user["telegram_id"],
                                "position_matches": body.position_matches,
                                "reports_preserved": sorted(report_dates),
                                "day_resolutions": body.day_resolutions,
                                "reports_before": reports_before,
                                "actor_name": request.state.user["name"],
                            },
                            ensure_ascii=False,
                        ),
                        now(),
                    ),
                )
                values = {
                    "source": meta["source"],
                    "source_name": meta["name"],
                    "last_import": now(),
                    "sheet_mappings": json.dumps(data["sheets"]),
                    "remote_days": json.dumps(remote_days),
                    "import_file_path": str(directory() / f"{body.token}.xlsx"),
                }
                if meta.get("remote", {}):
                    values["file_id"] = str(meta["remote"]["file_id"])
                for k, v in values.items():
                    store.set_setting(db, k, v)
                store.set_setting(
                    db,
                    "import_acknowledgements",
                    json.dumps(
                        {
                            "warnings": sorted(mandatory),
                            "actor": request.state.user["telegram_id"],
                            "at": now(),
                        }
                    ),
                )
                store.set_setting(db, "pending_import_token", "")
        return {
            "ok": True,
            "positions": len(data["positions"]),
            "source": meta["source"],
        }
