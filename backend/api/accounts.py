import os
from datetime import date
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request

from .. import bitrix, matcher, store, workspaces
from ..clock import today
from ..reporting import project_summary
from ..schemas import AiConnection, ProjectBody, UserBody
from ..security import admin

router = APIRouter()


@router.get("/api/session")
def session(request: Request, date: date | None = None):
    selected_date = date.isoformat() if date else today()
    return {
        "user": request.state.user,
        "projects": [
            project_summary(p, selected_date) for p in workspaces.visible(request.state.user)
        ],
        "mode": os.getenv("APP_ENV", "development"),
        "today": today(),
        "selected_date": selected_date,
        "ai_connected": bool(matcher.provider(workspaces.shared())["key"]),
    }


@router.get("/api/admin/users")
def users(request: Request):
    admin(request)
    with workspaces.registry() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT u.*,count(p.id) projects FROM users u LEFT JOIN projects p ON p.owner_id=u.telegram_id GROUP BY u.telegram_id ORDER BY u.role,u.name"
            )
        ]


@router.post("/api/admin/users")
def grant(request: Request, body: UserBody):
    admin(request)
    if body.telegram_id in workspaces.admins():
        raise HTTPException(409, "Главный администратор настроен на сервере")
    if body.telegram_id == request.state.user["telegram_id"] and (
        not body.enabled or body.role != "admin"
    ):
        raise HTTPException(409, "Нельзя отключить собственный доступ")
    with workspaces.registry() as db:
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,role=excluded.role,enabled=excluded.enabled",
            (body.telegram_id, body.name.strip(), body.role, int(body.enabled)),
        )
    return {"ok": True}


@router.post("/api/projects")
async def create_project(request: Request, body: ProjectBody):
    if not body.name.strip():
        raise HTTPException(422, "Укажите название объекта")
    try:
        if body.public_url:
            bitrix.validate_public(body.public_url)
        if body.webhook:
            bitrix.validate_webhook(body.webhook)
    except ValueError as e:
        raise HTTPException(422, str(e))
    p = workspaces.add_project(request.state.user, body.name.strip(), body.owner_id, body.sample)
    with store.connect(p["db_path"]) as db:
        for k, v in [
            ("public_url", body.public_url),
            ("file_id", str(body.file_id or 0)),
            ("webhook", body.webhook),
        ]:
            store.set_setting(db, k, v)
    return project_summary(p)


@router.post("/api/ai/connection")
async def ai_connection(request: Request, body: AiConnection):
    admin(request)
    p = urlparse(body.base_url)
    if (
        p.scheme != "https"
        or p.hostname not in {"api.openai.com", "api.deepseek.com", "api.groq.com", "openrouter.ai"}
        or p.username
        or p.password
    ):
        raise HTTPException(422, "Укажите HTTPS API OpenAI, DeepSeek, Groq или OpenRouter")
    settings = {
        "llm_api_key": body.api_key,
        "llm_base_url": body.base_url,
        "llm_model": body.model,
    }
    try:
        result = await matcher.complete(
            'Ответь JSON {"ok":true}.', "Проверка подключения", settings
        )
        if result.get("ok") is not True:
            raise ValueError()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(400, "Не удалось подключить AI. Проверьте ключ, адрес и модель.")
    workspaces.set_shared(settings)
    return {"ok": True}
