import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import store, workspaces
from ..clock import now
from ..imports import remove_project_imports
from ..synchronization import table_lock

router = APIRouter(prefix="/api/object")


def owned_object(request):
    project = request.state.project
    user = request.state.user
    if user["role"] != "master" or user["telegram_id"] != project["owner_id"]:
        raise HTTPException(403, "Управление доступно мастеру-владельцу объекта")
    return project


def position_usage(db):
    used = {row[0] for row in db.execute("SELECT DISTINCT item_id FROM entries")}
    used.update(row[0] for row in db.execute("SELECT id FROM positions WHERE baseline<>0"))
    for row in db.execute("SELECT payload FROM day_snapshots"):
        used.update(line["item_id"] for line in json.loads(row[0]).get("lines", []))
    for row in db.execute("SELECT payload FROM audit"):
        event = json.loads(row[0])
        used.update(line["item_id"] for line in event.get("before", {}).get("lines", []))
        used.update(line["item_id"] for line in event.get("changes", {}).get("lines", []))
    return used


@router.get("/management")
def management(request: Request):
    owned_object(request)
    with store.connect() as db:
        return {
            "reports": db.execute("SELECT count(*) FROM reports").fetchone()[0],
            "pending": db.execute(
                "SELECT count(*) FROM reports WHERE sync_status IN ('pending','error')"
            ).fetchone()[0],
            "used_positions": sorted(position_usage(db)),
        }


class DeleteObject(BaseModel):
    name: str


@router.post("/delete")
async def delete(request: Request, body: DeleteObject):
    project = owned_object(request)
    if body.name.strip() != project["name"]:
        raise HTTPException(422, "Введите точное название объекта")
    async with table_lock(project):
        workspaces.delete_project(project)
        remove_project_imports(project["id"])
    return {"ok": True}


@router.post("/table/detach")
async def detach(request: Request):
    project = owned_object(request)
    async with table_lock(project):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if store.setting(db, "source") == "bitrix":
                store.set_setting(db, "source", "detached")
            for key, value in {
                "public_url": "",
                "file_id": "0",
                "webhook": "",
                "connection_check": "null",
                "table_detail_url": "",
                "pending_import_token": "",
            }.items():
                store.set_setting(db, key, value)
            db.execute(
                "UPDATE reports SET sync_status='pending',sync_error=?,retry_at='',sync_attempts=0 "
                "WHERE sync_status IN ('pending','error')",
                ("Таблица отвязана. Отчёт сохранён в приложении.",),
            )
    return {"ok": True}


class PositionAction(BaseModel):
    action: str


@router.post("/positions/{position_id}")
async def update_position(request: Request, position_id: str, body: PositionAction):
    project = owned_object(request)
    if body.action not in ("delete", "hide", "show"):
        raise HTTPException(422, "Выберите действие с работой")
    async with table_lock(project):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            position = db.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
            if position is None:
                raise HTTPException(404, "Работа отсутствует в смете")
            hidden = store.hidden_positions(db)
            if body.action == "delete":
                if position_id in position_usage(db):
                    raise HTTPException(
                        409, "Работа используется в истории. Её можно скрыть из подбора."
                    )
                db.execute("DELETE FROM positions WHERE id=?", (position_id,))
                hidden.pop(position_id, None)
            elif body.action == "hide":
                hidden[position_id] = store.position_identity(position)
            else:
                hidden.pop(position_id, None)
            store.set_setting(db, "hidden_positions", json.dumps(hidden, ensure_ascii=False))
            db.execute(
                "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
                (
                    now()[:10],
                    json.dumps(
                        {
                            "action": "catalogue_position_" + body.action,
                            "position_name": position["name"],
                            "actor_name": request.state.user["name"],
                            "actor_id": request.state.user["telegram_id"],
                        },
                        ensure_ascii=False,
                    ),
                    now(),
                ),
            )
    return {"ok": True}
