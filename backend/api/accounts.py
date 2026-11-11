import json
import os
from datetime import date
from urllib.parse import parse_qsl, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import bitrix, matcher, store, workspaces
from ..clock import today
from ..reporting import project_summary
from ..schemas import AiConnection, ProjectBody, UserBody
from ..security import admin

router = APIRouter()


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/api/profile")
def update_profile(request: Request, body: ProfileBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Укажите имя")
    with workspaces.registry() as database:
        database.execute(
            "UPDATE users SET name=?,custom_name=1 WHERE telegram_id=?",
            (name, request.state.user["telegram_id"]),
        )
    return {"ok": True}


@router.get("/api/session")
def session(request: Request, date: date | None = None):
    if os.getenv("APP_ENV", "development") == "production":
        raw = dict(parse_qsl(request.headers.get("X-Telegram-Init-Data", "")))
        profile = json.loads(raw.get("user", "{}"))
        with workspaces.registry() as database:
            name = " ".join(
                filter(None, [profile.get("first_name"), profile.get("last_name")])
            ).strip()
            photo = profile.get("photo_url", "")
            if photo and urlparse(photo).scheme != "https":
                photo = ""
            database.execute(
                "UPDATE users SET avatar_url=?,username=?,name=CASE WHEN custom_name=0 AND ?<>'' THEN ? ELSE name END WHERE telegram_id=?",
                (photo, profile.get("username", ""), name, name, request.state.user["telegram_id"]),
            )
            if photo != request.state.user.get("avatar_url", ""):
                database.execute(
                    "DELETE FROM profile_avatars WHERE telegram_id=?",
                    (request.state.user["telegram_id"],),
                )
        refreshed = workspaces.user(request.state.user["telegram_id"])
        request.state.user = {**refreshed, "role": request.state.user["role"]}
    selected_date = date.isoformat() if date else today()
    return {
        "user": request.state.user,
        "projects": [
            project_summary(
                p, selected_date, include_table_review=request.state.user["role"] == "master"
            )
            for p in workspaces.visible(request.state.user)
        ],
        "mode": os.getenv("APP_ENV", "development"),
        "today": today(),
        "selected_date": selected_date,
        "ai_connected": bool(matcher.provider(workspaces.shared())["key"]),
        "can_switch_role": request.state.can_switch_role,
        "view_mode": request.state.user["role"],
    }


@router.get("/api/admin/users")
def users(request: Request):
    admin(request)
    with workspaces.registry() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT u.*,count(p.id) projects FROM users u LEFT JOIN projects p ON p.owner_id=u.telegram_id WHERE u.enabled=1 GROUP BY u.telegram_id ORDER BY u.role,u.name"
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
            "INSERT INTO users(telegram_id,name,role,enabled) VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,role=excluded.role,enabled=excluded.enabled",
            (body.telegram_id, body.name.strip(), body.role, int(body.enabled)),
        )
    return {"ok": True}


@router.post("/api/admin/users/{telegram_id}/delete")
def delete_user(request: Request, telegram_id: str):
    admin(request)
    if telegram_id in workspaces.admins() or telegram_id in (
        request.state.user["telegram_id"],
        "local-admin",
    ):
        raise HTTPException(409, "Собственный аккаунт и главного администратора удалить нельзя")
    with workspaces.registry() as db:
        db.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (telegram_id,))
        db.execute("DELETE FROM profile_avatars WHERE telegram_id=?", (telegram_id,))
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
