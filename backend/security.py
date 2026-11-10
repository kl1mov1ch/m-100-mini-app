import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import store, workspaces


def telegram_identity(raw):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    pairs = parse_qsl(raw, keep_blank_values=True)
    if len(dict(pairs)) != len(pairs):
        return None
    data = dict(pairs)
    received = data.pop("hash", "")
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret,
        "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        age = time.time() - int(data.get("auth_date", 0))
        identity = json.loads(data.get("user", "{}"))
        return (
            str(identity["id"])
            if hmac.compare_digest(received, expected) and 0 <= age <= 3600
            else None
        )
    except (ValueError, KeyError, TypeError):
        return None


def validate_init_data(raw):
    return telegram_identity(raw) is not None


async def access(request: Request, call_next):
    token = None
    try:
        if request.url.path.startswith("/api"):
            origin = request.headers.get("origin")
            allowed_origins = {request.url.scheme + "://" + request.headers.get("host", "")}
            allowed_origins.update(
                value.strip().rstrip("/")
                for value in os.getenv("APP_ALLOWED_ORIGINS", "").split(",")
                if value.strip()
            )
            if os.getenv("APP_ENV", "development") == "development":
                allowed_origins.update(
                    {
                        "http://127.0.0.1:5173",
                        "http://localhost:5173",
                        "http://127.0.0.1:8000",
                        "http://localhost:8000",
                    }
                )
            if origin and origin.rstrip("/") not in allowed_origins:
                raise HTTPException(403, "Запрос с другого сайта запрещён")
            if os.getenv("APP_ENV", "development") == "development":
                ident = request.headers.get("X-Preview-User", "local-admin")
            else:
                ident = telegram_identity(request.headers.get("X-Telegram-Init-Data", ""))
                if not ident:
                    raise HTTPException(401, "Откройте приложение через Telegram")
            request.state.user = workspaces.user(ident)
            unscoped = ("/api/session", "/api/projects", "/api/admin", "/api/ai")
            if not any(
                request.url.path == p or request.url.path.startswith(p + "/") for p in unscoped
            ):
                p = workspaces.project(request.state.user, request.headers.get("X-Project-Id"))
                request.state.project = p
                token = store.CURRENT_DATABASE.set(p["db_path"])
        return await call_next(request)
    except HTTPException as e:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    finally:
        if token is not None:
            store.CURRENT_DATABASE.reset(token)


def admin(request):
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "Доступно только администратору")
