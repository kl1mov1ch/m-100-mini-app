import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import workspaces
from .security import REPORT_DOWNLOAD_PATH, can_switch_role

router = APIRouter()
DOWNLOAD_TTL = 300
MAX_PENDING_DOWNLOADS = 256
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}


@dataclass(frozen=True)
class ReportDownload:
    telegram_id: str
    role: str
    filename: str
    content_type: str
    render: Callable[[dict], bytes]
    expires: float


downloads: dict[str, ReportDownload] = {}
downloads_lock = Lock()


def file_response(content, filename, content_type):
    return Response(
        content,
        media_type=content_type,
        headers={
            **PRIVATE_HEADERS,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Allow-Origin": "https://web.telegram.org",
            "Access-Control-Expose-Headers": "Content-Disposition",
            "X-Content-Type-Options": "nosniff",
        },
    )


def report_export(user, filename, content_type, render, prepare):
    if not prepare:
        return file_response(render(user), filename, content_type)
    token = secrets.token_urlsafe(32)
    with downloads_lock:
        current_time = time.monotonic()
        for expired in [key for key, item in downloads.items() if item.expires <= current_time]:
            del downloads[expired]
        if len(downloads) >= MAX_PENDING_DOWNLOADS:
            raise HTTPException(429, "Много запросов на скачивание. Попробуйте чуть позже.")
        downloads[token] = ReportDownload(
            user["telegram_id"],
            user["role"],
            filename,
            content_type,
            render,
            current_time + DOWNLOAD_TTL,
        )
    return JSONResponse(
        {"url": f"{REPORT_DOWNLOAD_PATH}{token}/{filename}", "filename": filename},
        headers=PRIVATE_HEADERS,
    )


@router.api_route(
    REPORT_DOWNLOAD_PATH + "{token}/{filename}", methods=["GET", "HEAD"], include_in_schema=False
)
def download_report(request: Request, token: str, filename: str):
    with downloads_lock:
        download = downloads.get(token)
        if download and download.expires <= time.monotonic():
            del downloads[token]
            download = None
    if not download or filename != download.filename:
        raise HTTPException(404, "Ссылка истекла. Скачайте отчёт ещё раз.")
    user = workspaces.user(download.telegram_id)
    if user["role"] != download.role:
        if download.role != "master" or not can_switch_role(user):
            raise HTTPException(403, "Доступ к отчёту изменился")
        user = {**user, "role": "master"}
    content = download.render(user) if request.method == "GET" else b""
    response = file_response(content, download.filename, download.content_type)
    if request.method == "HEAD":
        del response.headers["content-length"]
    return response
