import json
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import bitrix, store, tables


class ConfirmImport(BaseModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    sheets: list[dict]
    acknowledged: list[str] = []


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
        return {"token": token, "name": name, "source": source, **analysis}

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
            data = tables.extract(content, body.sheets)
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
        }

    @app.post("/api/imports/confirm")
    async def confirm(request: Request, body: ConfirmImport):
        meta, content = read_pending(body.token, request.state.project["id"])
        try:
            data = tables.extract(content, body.sheets)
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
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = [dict(r) for r in db.execute("SELECT * FROM positions")]
            fresh = {p["id"]: p for p in data["positions"]}
            has_reports = db.execute("SELECT 1 FROM reports LIMIT 1").fetchone()
            if has_reports and any(
                p["id"] not in fresh or p["name"] != fresh[p["id"]]["name"] for p in before
            ):
                raise HTTPException(
                    409,
                    "Смета относится к другому объекту или строки изменились. Добавьте её отдельным объектом, чтобы сохранить существующие отчёты.",
                )
            preserved = [
                dict(r)
                for r in db.execute(
                    "SELECT e.* FROM entries e JOIN reports r ON r.date=e.date WHERE r.sync_status!='synced'"
                )
            ]
            dirty = {r["date"] for r in preserved}
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
            db.execute("UPDATE reports SET revision=revision+1 WHERE sync_status='synced'")
            values = {
                "source": meta["source"],
                "source_name": meta["name"],
                "last_import": now(),
                "sheet_mappings": json.dumps(body.sheets),
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
