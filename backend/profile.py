import asyncio
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import workspaces

router = APIRouter()
AVATAR_LIMIT = asyncio.Semaphore(4)


def avatar_response(content, mime):
    return Response(content, media_type=mime, headers={"Cache-Control": "no-store"})


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
            base = "https://api.telegram.org/bot" + token + "/"
            photos = (
                await client.post(
                    base + "getUserProfilePhotos", data={"user_id": target_id, "limit": "1"}
                )
            ).json()
            if not photos.get("ok"):
                raise ValueError("Telegram временно не предоставил фото")
            if not photos.get("result", {}).get("photos"):
                with workspaces.registry() as database:
                    database.execute(
                        "INSERT INTO profile_avatars(telegram_id,content,mime,checked_at) VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET content=excluded.content,mime=excluded.mime,checked_at=excluded.checked_at",
                        (target_id, b"", "image/jpeg", int(time.time())),
                    )
                raise HTTPException(404, "Фото профиля недоступно боту")
            photo = photos["result"]["photos"][0][-1]
            metadata = (
                await client.post(base + "getFile", data={"file_id": photo["file_id"]})
            ).json()
            if not metadata.get("ok"):
                raise ValueError("Telegram не предоставил фото")
            response = await client.get(
                "https://api.telegram.org/file/bot" + token + "/" + metadata["result"]["file_path"]
            )
            response.raise_for_status()
            if not response.content or len(response.content) > 2 * 1024 * 1024:
                raise ValueError("Некорректное фото")
            mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                mime = "image/jpeg"
            with workspaces.registry() as database:
                database.execute(
                    "INSERT INTO profile_avatars(telegram_id,content,mime,checked_at) VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET content=excluded.content,mime=excluded.mime,checked_at=excluded.checked_at",
                    (target_id, response.content, mime, int(time.time())),
                )
            return avatar_response(response.content, mime)
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        if cached and cached["content"]:
            return avatar_response(cached["content"], cached["mime"])
        raise HTTPException(404, "Фото временно недоступно")
