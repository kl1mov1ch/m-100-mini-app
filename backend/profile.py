import asyncio
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import profile_webhooks, store, workspaces

router = APIRouter()
AVATAR_LIMIT = asyncio.Semaphore(4)


class DiskWebhook(BaseModel):
    name: str = Field(default="", max_length=80)
    url: str = Field(default="", max_length=500)
    project_id: str | None = Field(default=None, max_length=64)


def master_profile(request):
    user = request.state.user
    if user["role"] != "master":
        raise HTTPException(403, "Вебхуки доступны в профиле мастера")
    return user


@router.get("/api/profile/disk-webhooks")
def disk_webhooks(request: Request):
    return profile_webhooks.list_webhooks(master_profile(request)["telegram_id"])


@router.post("/api/profile/disk-webhooks")
def add_disk_webhook(request: Request, body: DiskWebhook):
    user = master_profile(request)
    url = body.url
    if body.project_id:
        project = workspaces.project(user, body.project_id)
        with store.connect(project["db_path"]) as db:
            url = store.setting(db, "webhook")
    try:
        return profile_webhooks.save_webhook(user["telegram_id"], body.name, url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/profile/disk-webhooks/{ident}/update")
def update_disk_webhook(ident: str, request: Request, body: DiskWebhook):
    user = master_profile(request)
    try:
        return profile_webhooks.update_webhook(user["telegram_id"], ident, body.name, body.url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/profile/disk-webhooks/{ident}/delete")
def delete_disk_webhook(ident: str, request: Request):
    return profile_webhooks.delete_webhook(master_profile(request)["telegram_id"], ident)


def avatar_response(content, mime):
    return Response(
        content,
        media_type=mime,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


def save_avatar(telegram_id, content, mime):
    with workspaces.registry() as database:
        database.execute(
            "INSERT INTO profile_avatars(telegram_id,content,mime,checked_at) VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET content=excluded.content,mime=excluded.mime,checked_at=excluded.checked_at",
            (telegram_id, content, mime, int(time.time())),
        )


def telegram_photo_url(value):
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "t.me"
        and parsed.path.startswith("/i/userpic/")
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
    )


async def download_photo(client, url):
    response = await client.get(url)
    response.raise_for_status()
    mime = response.headers.get("content-type", "").split(";")[0].strip()
    if (
        not response.content
        or len(response.content) > 2 * 1024 * 1024
        or mime not in ("image/jpeg", "image/png", "image/webp", "image/svg+xml")
    ):
        raise ValueError("Некорректное фото")
    return response.content, mime


@router.get("/api/profile/avatar")
async def avatar(request: Request, user_id: str | None = None, refresh: bool = False):
    current_id = request.state.user["telegram_id"]
    target_id = user_id or current_id
    if target_id != current_id and request.state.user["role"] != "admin":
        raise HTTPException(403, "Чужой профиль недоступен")
    if not target_id.isdigit():
        target_id = (
            next(iter(workspaces.admins()), "")
            if target_id == "local-admin" and os.getenv("APP_ENV", "development") == "development"
            else ""
        )
    if not target_id:
        raise HTTPException(404, "Аватар недоступен")
    with workspaces.registry() as database:
        cached = database.execute(
            "SELECT * FROM profile_avatars WHERE telegram_id=?", (target_id,)
        ).fetchone()
        user = database.execute(
            "SELECT avatar_url FROM users WHERE telegram_id=?", (target_id,)
        ).fetchone()
    photo_url = user["avatar_url"] if user else ""
    if cached and not refresh and time.time() - cached["checked_at"] < 300:
        if cached["content"]:
            return avatar_response(cached["content"], cached["mime"])
        raise HTTPException(404, "Фото профиля не установлено")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(404, "Бот не подключён")
    try:
        async with (
            AVATAR_LIMIT,
            httpx.AsyncClient(timeout=15, proxy=os.getenv("TELEGRAM_PROXY_URL") or None) as client,
        ):
            if telegram_photo_url(photo_url):
                try:
                    content, mime = await download_photo(client, photo_url)
                    save_avatar(target_id, content, mime)
                    return avatar_response(content, mime)
                except (httpx.HTTPError, ValueError):
                    pass
            base = "https://api.telegram.org/bot" + token + "/"
            photos = (
                await client.post(
                    base + "getUserProfilePhotos", data={"user_id": target_id, "limit": "1"}
                )
            ).json()
            if not photos.get("ok"):
                raise ValueError("Telegram временно не предоставил фото")
            if not photos.get("result", {}).get("photos"):
                save_avatar(target_id, b"", "image/jpeg")
                raise HTTPException(404, "Фото профиля недоступно боту")
            photo = photos["result"]["photos"][0][-1]
            metadata = (
                await client.post(base + "getFile", data={"file_id": photo["file_id"]})
            ).json()
            if not metadata.get("ok"):
                raise ValueError("Telegram не предоставил фото")
            content, mime = await download_photo(
                client,
                "https://api.telegram.org/file/bot" + token + "/" + metadata["result"]["file_path"],
            )
            save_avatar(target_id, content, mime)
            return avatar_response(content, mime)
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        if cached and cached["content"]:
            return avatar_response(cached["content"], cached["mime"])
        raise HTTPException(404, "Фото временно недоступно")
