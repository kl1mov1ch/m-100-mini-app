import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from . import (
    bitrix,
    import_suggestions,
    reconciliation,
    store,
    tables,
    workbook_revision,
    workspaces,
)
from .report_downloads import report_export
from .synchronization import JOURNAL_PENDING_NOTE, table_lock, write_journal
from .table_advice import explain_issues, with_tips
from .workbook_journal import format_journal


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


def remove_project_imports(project_id):
    for metadata in (store.base_path().parent / "imports").glob("*.json"):
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("project_id") == project_id:
                metadata.with_suffix(".xlsx").unlink(missing_ok=True)
                metadata.with_suffix(".journal.xlsx").unlink(missing_ok=True)
                metadata.with_suffix(".source.xlsx").unlink(missing_ok=True)
                metadata.unlink(missing_ok=True)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("Could not remove an object import")


def read_pending(token, project):
    try:
        meta = json.loads((directory() / f"{token}.json").read_text(encoding="utf-8"))
        if meta["project_id"] != project:
            raise HTTPException(403, "Эта таблица принадлежит другому объекту")
        return meta, (directory() / f"{token}.xlsx").read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "Импорт не найден. Загрузите файл снова.")


def save_pending(meta, content):
    token = uuid.uuid4().hex
    (directory() / f"{token}.xlsx").write_bytes(content)
    if meta.get("original"):
        original_snapshot(token).write_bytes(content)
    (directory() / f"{token}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    with store.connect() as db:
        store.set_setting(db, "pending_import_token", token)
    return token


def original_snapshot(token):
    return directory() / f"{token}.source.xlsx"


def check_latest(original, latest, metadata):
    difference = workbook_revision.changes(original, latest)
    if not difference:
        return
    try:
        if difference["kind"] == "appearance":
            sheets, warnings = metadata["sheets"], []
        else:
            sheets, warnings = tables.discover(latest, original=metadata.get("original", False))
        analysis = tables.extract(latest, sheets)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    save_pending(
        {
            **metadata,
            "sheets": sheets,
            "warnings": warnings + analysis["warnings"],
            "source_change": difference,
        },
        latest,
    )
    raise HTTPException(
        409,
        {"code": "workbook_changed", "message": "Таблица обновилась. Открыта актуальная проверка."},
    )


async def verify_pending_remote(token, meta, content):
    with store.connect() as db:
        pending = store.setting(db, "pending_import_token")
        file_id = int(store.setting(db, "file_id", "0"))
        webhook = store.setting(db, "webhook")
        url = store.setting(db, "public_url")
    if meta.get("original") and (not webhook or not file_id):
        raise HTTPException(
            422, "Для обновления рабочих листов нужен вебхук Битрикс24 с правом «Диск»."
        )
    if token != pending or (
        file_id and file_id != int((meta.get("remote") or {}).get("file_id") or 0)
    ):
        raise HTTPException(
            409, {"code": "workbook_changed", "message": "Открыта текущая проверка таблицы."}
        )
    try:
        latest, _ = await (
            bitrix.download_rest(webhook, file_id)
            if webhook and file_id
            else bitrix.fetch_public(url)
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(502, "Битрикс24 не отдал текущую книгу. Повторите проверку.") from error
    if meta.get("original"):
        content = original_snapshot(token).read_bytes()
        difference = await asyncio.to_thread(
            workbook_revision.changes, content, latest, original_only=True
        )
        if not difference:
            return
    check_latest(content, latest, meta)


def register(app, settings, now):
    @app.get("/api/imports/journal-status")
    def journal_status(request: Request):
        with store.connect(request.state.project["db_path"]) as db:
            return {
                "journal_status": store.setting(db, "journal_status"),
                "journal_note": store.setting(db, "journal_note"),
            }

    @app.get("/api/imports/workbook.xlsx")
    def normalized_workbook(request: Request, prepare: bool = False):
        if request.state.user["role"] != "master":
            raise HTTPException(403, "Таблица доступна мастеру объекта")
        project_id = request.state.project["id"]

        def render(user):
            project = workspaces.project(user, project_id)
            with store.connect(project["db_path"]) as db:
                raw = store.setting(db, "import_file_path")
                file = Path(raw)
                if (
                    store.setting(db, "source") != "file"
                    or not raw
                    or file.parent != directory()
                    or not file.is_file()
                ):
                    raise HTTPException(404, "Загрузите Excel для этого объекта")
                positions, entries, crew = journal_data(db)
                content = file.read_bytes()
                mappings = json.loads(store.setting(db, "sheet_mappings", "null"))
            return format_journal(content, positions, entries, crew, [], mappings)

        return report_export(
            request.state.user,
            "work-journal.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            render,
            prepare,
        )

    async def prepare(
        request, content, name, source, remote=None, *, original=False, source_change=None
    ):
        with store.connect() as db:
            cfg = settings(db)
        try:
            analysis = await tables.analyze(content, cfg, original=original)
        except ValueError as e:
            raise HTTPException(422, str(e))
        meta = {
            "project_id": request.state.project["id"],
            "owner_id": request.state.user["telegram_id"],
            "name": name,
            "source": source,
            "remote": remote,
            "original": original,
            "source_change": source_change,
            "warnings": analysis["warnings"],
            "sheets": analysis["sheets"],
            "created_at": now(),
        }
        token = save_pending(meta, content)
        return {
            "token": token,
            "name": name,
            "source": source,
            **analysis,
            "source_change": source_change,
            "reconciliation": current_reconciliation(analysis),
        }

    @app.get("/api/imports/pending")
    async def pending(request: Request):
        if request.state.user["role"] != "master":
            return None
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
            "source_change": meta.get("source_change"),
            "warnings": with_tips(
                structural + data["warnings"],
                {
                    warning["id"]: warning["ai_tip"]
                    for warning in meta["warnings"]
                    if warning.get("ai_tip")
                },
            ),
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
    async def remote(request: Request, original: bool = False):
        with store.connect() as db:
            webhook = store.setting(db, "webhook")
            file_id = int(store.setting(db, "file_id", "0"))
            url = store.setting(db, "public_url")
            previous_file = store.setting(db, "import_file_path")
        if not webhook and not url:
            raise HTTPException(422, "Сначала укажите ссылку на таблицу Битрикс24")
        try:
            if webhook:
                content, meta = await bitrix.download_rest(webhook, file_id)
                remote = {"name": meta["NAME"], "file_id": file_id}
            else:
                content, meta = await bitrix.fetch_public(url)
                remote = meta
            difference = None
            if original and previous_file:
                previous = Path(previous_file)
                if previous.parent == directory() and previous.is_file():
                    difference = await asyncio.to_thread(
                        workbook_revision.changes,
                        previous.read_bytes(),
                        content,
                        original_only=True,
                    )
                    if not difference:
                        return None
            return await prepare(
                request,
                content,
                remote["name"],
                "bitrix",
                remote,
                original=original,
                source_change=difference,
            )
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
        with store.connect() as db:
            cfg = settings(db)
        warnings = old + data["warnings"]
        return {
            "token": body.token,
            "name": meta["name"],
            "source": meta["source"],
            **data,
            "source_change": meta.get("source_change"),
            "warnings": with_tips(warnings, await explain_issues(warnings, cfg)),
            "reconciliation": current_reconciliation(data),
        }

    @app.post("/api/imports/consult")
    async def consult(request: Request, body: ConfirmImport):
        if request.state.user["role"] != "master":
            raise HTTPException(403, "Таблицу проверяет мастер объекта")
        _, content = read_pending(body.token, request.state.project["id"])
        try:
            data = tables.extract(content, import_sheets(body.sheets))
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, str(error)) from error
        with store.connect() as db:
            suggestions, unknown_units = import_suggestions.verified_options(db, data)
            cfg = settings(db)
            for warning in data["warnings"]:
                if not warning.get("affected_rows"):
                    continue
                saved = import_suggestions.restore_day_values(
                    db, data["positions"], warning["date"]
                )
                count = sum(
                    position["id"] in saved
                    for position in data["positions"]
                    if position["source_sheet"] == warning["sheet"]
                    and position["source_row"] in warning["affected_rows"]
                )
                suggestions[warning["id"]] = {
                    "options": [],
                    "message": "",
                    "restore_count": count,
                }
        units = await import_suggestions.suggest_units(unknown_units, cfg)
        for item in unknown_units:
            ident = item["id"]
            unit = units.get(ident)
            if unit in import_suggestions.STANDARD_UNITS:
                suggestions[ident] = {
                    "options": [
                        import_suggestions.candidate(
                            unit, "Вариант ИИ по названию работы. Сверьте с проектом."
                        )
                    ],
                    "message": "",
                }
        return suggestions

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
    async def confirm(request: Request, body: ConfirmImport, background: BackgroundTasks):
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
            if meta["source"] == "bitrix":
                await verify_pending_remote(body.token, meta, content)
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
                position_fields = ("name", "planned", "rate", "unit")
                old_positions = {
                    position["id"]: {field: position[field] for field in position_fields}
                    for position in store.positions(db)
                }
                position_updates = {}
                for position in data["positions"]:
                    before = old_positions.get(position["id"])
                    after = {field: position[field] for field in position_fields}
                    if before and before != after:
                        position_updates[position["id"]] = {"before": before, "after": after}
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
                store.restore_hidden_positions(db, data["positions"])
                for e in data["entries"]:
                    db.execute(
                        "INSERT INTO entries(item_id,date,quantity) VALUES(:item_id,:date,:quantity) ON CONFLICT(item_id,date) DO UPDATE SET quantity=entries.quantity+excluded.quantity",
                        e,
                    )
                for day in dirty:
                    db.execute("DELETE FROM entries WHERE date=?", (day,))
                for e in preserved:
                    db.execute(
                        "INSERT INTO entries(item_id,date,quantity) VALUES(:item_id,:date,:quantity)",
                        e,
                    )
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
                            "UPDATE reports SET revision=revision+1,sync_status=?,sync_error='',retry_at='',sync_attempts=0 WHERE date=?",
                            ("synced" if meta["source"] == "bitrix" else "pending", report_day),
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
                                "position_updates": position_updates,
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
                    "import_file_path": str(
                        original_snapshot(body.token)
                        if meta.get("original")
                        else directory() / f"{body.token}.xlsx"
                    ),
                    "bitrix_read_status": "null",
                    "bitrix_read_positions": "{}",
                    "bitrix_read_days": "{}",
                    "connection_check": "null",
                    "bitrix_appearance": "null",
                    "bitrix_appearance_observed": "null",
                    "journal_status": "pending" if meta["source"] == "bitrix" else "",
                    "journal_note": JOURNAL_PENDING_NOTE if meta["source"] == "bitrix" else "",
                    "journal_retry_at": "",
                    "journal_rebuild": "1"
                    if meta["source"] == "bitrix" and meta.get("original")
                    else "",
                }
                if meta["source"] == "file":
                    positions, entries, crew = journal_data(db)
                    path = directory() / f"{body.token}.journal.xlsx"
                    temporary = path.with_suffix(".tmp")
                    temporary.write_bytes(
                        format_journal(content, positions, entries, crew, [], data["sheets"])
                    )
                    temporary.replace(path)
                    values["import_file_path"] = str(path)
                if meta.get("remote", {}):
                    values["file_id"] = str(meta["remote"]["file_id"] or 0)
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
        journal = None
        if meta["source"] == "bitrix":
            background.add_task(write_journal, request.state.project)
            journal = {"status": "pending", "message": JOURNAL_PENDING_NOTE}
        return {
            "ok": True,
            "positions": len(data["positions"]),
            "source": meta["source"],
            "journal": journal,
        }


def journal_data(db):
    positions = store.positions(db)
    entries = [dict(row) for row in db.execute("SELECT item_id,date,quantity FROM entries")]
    crew = {
        row["date"]: row["crew_count"] for row in db.execute("SELECT date,crew_count FROM reports")
    }
    return positions, entries, crew
