import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import store, workspaces
from .clock import MINSK_TIMEZONE, now, today
from .security import admin

router = APIRouter()
DEFAULT_TEXT = "Пожалуйста, отправьте отчёт за сегодня в журнале работ."
Audience = Literal["missing", "selected", "all"]


class ReminderSettings(BaseModel):
    enabled: bool = False
    weekdays: list[int] = Field(default=[0, 1, 2, 3, 4], min_length=1, max_length=7)
    time: str = Field(default="16:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    text: str = Field(default=DEFAULT_TEXT, min_length=1, max_length=1500)
    audience: Audience = "missing"
    recipient_ids: list[str] = Field(default_factory=list)


class SendReminders(BaseModel):
    request_id: uuid.UUID
    audience: Audience | None = None
    recipient_ids: list[str] = Field(default_factory=list)
    text: str | None = Field(default=None, min_length=1, max_length=1500)


def settings():
    return ReminderSettings.model_validate(json.loads(workspaces.shared().get("reminders", "{}")))


def missing_reports(day):
    with workspaces.registry() as registry:
        projects = [
            dict(row)
            for row in registry.execute(
                "SELECT p.*, u.name owner_name FROM projects p JOIN users u ON u.telegram_id=p.owner_id WHERE u.enabled=1 AND u.role='master'"
            )
        ]
    recipients = {}
    for project in projects:
        with store.connect(project["db_path"]) as database:
            if not database.execute("SELECT 1 FROM positions LIMIT 1").fetchone():
                continue
            submitted = database.execute(
                "SELECT 1 FROM entries WHERE date=? LIMIT 1",
                (day,),
            ).fetchone()
        if not submitted:
            recipient = recipients.setdefault(
                project["owner_id"],
                {"telegram_id": project["owner_id"], "name": project["owner_name"], "projects": []},
            )
            recipient["projects"].append(project["name"])
    return list(recipients.values())


def telegram_users():
    with workspaces.registry() as database:
        return [
            dict(row)
            for row in database.execute(
                "SELECT telegram_id, name, role FROM users WHERE enabled=1 ORDER BY name, telegram_id"
            )
            if row["telegram_id"].isdigit()
        ]


def send_to(day, audience, recipient_ids):
    if audience == "missing":
        return missing_reports(day)
    selected = set(recipient_ids)
    return [
        recipient
        for recipient in telegram_users()
        if audience == "all" or recipient["telegram_id"] in selected
    ]


async def deliver(day, run_key, selected_recipients=None, message_override=None):
    config = settings()
    recipients = (
        send_to(day, config.audience, config.recipient_ids)
        if selected_recipients is None
        else selected_recipients
    )
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": 0}
    public_url = os.getenv("APP_PUBLIC_URL", "").rstrip("/")
    if not public_url.startswith("https://"):
        raise ValueError("Задайте HTTPS-адрес приложения на сервере")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("Бот не подключён")
    result = {"sent": 0, "failed": 0, "skipped": 0}
    async with httpx.AsyncClient(
        timeout=20, proxy=os.getenv("TELEGRAM_PROXY_URL") or None
    ) as client:
        for recipient in recipients:
            with workspaces.registry() as database:
                inserted = database.execute(
                    "INSERT INTO reminder_deliveries VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(telegram_id,day,run_key) DO NOTHING",
                    (recipient["telegram_id"], day, run_key, "sending", "", now()),
                )
                if inserted.rowcount != 1:
                    result["skipped"] += 1
                    continue
            message = message_override if message_override is not None else config.text.strip()
            if projects := recipient.get("projects"):
                message += "\n\nБез отчёта за " + datetime.fromisoformat(day).strftime("%d.%m.%Y")
                message += ":\n" + "\n".join("• " + name for name in projects)
            status, error = "sent", ""
            try:
                response = await client.post(
                    "https://api.telegram.org/bot" + token + "/sendMessage",
                    data={
                        "chat_id": recipient["telegram_id"],
                        "text": message[:4000],
                        "reply_markup": json.dumps(
                            {
                                "inline_keyboard": [
                                    [
                                        {
                                            "text": "Открыть журнал работ",
                                            "web_app": {"url": public_url},
                                        }
                                    ]
                                ]
                            }
                        ),
                    },
                )
                payload = response.json()
                if not payload.get("ok"):
                    status = "failed"
                    error = (
                        "Мастер может разрешить уведомления в настройках приложения"
                        if response.status_code in (400, 403)
                        else "Telegram не принял сообщение; повторите отправку"
                    )
            except (httpx.HTTPError, ValueError):
                status, error = "failed", "Не удалось связаться с Telegram"
            with workspaces.registry() as database:
                database.execute(
                    "UPDATE reminder_deliveries SET status=?,error=?,created_at=? WHERE telegram_id=? AND day=? AND run_key=?",
                    (status, error, now(), recipient["telegram_id"], day, run_key),
                )
            result["sent" if status == "sent" else "failed"] += 1
    return result


@router.get("/api/admin/reminders")
def configuration(request: Request):
    admin(request)
    with workspaces.registry() as database:
        deliveries = [
            dict(row)
            for row in database.execute(
                "SELECT d.*, u.name FROM reminder_deliveries d LEFT JOIN users u ON d.telegram_id=u.telegram_id ORDER BY created_at DESC LIMIT 50"
            )
        ]
    return {
        "settings": settings(),
        "recipients": missing_reports(today()),
        "users": telegram_users(),
        "deliveries": deliveries,
        "timezone": "Europe/Minsk",
    }


@router.post("/api/admin/reminders/settings")
def save_settings(request: Request, body: ReminderSettings):
    admin(request)
    if not body.text.strip():
        raise HTTPException(422, "Введите текст напоминания")
    if any(day < 0 or day > 6 for day in body.weekdays):
        raise HTTPException(422, "Выберите дни недели с понедельника по воскресенье")
    if body.audience == "selected" and not body.recipient_ids:
        raise HTTPException(422, "Выберите получателей")
    workspaces.set_shared({"reminders": body.model_dump_json()})
    return {"ok": True}


@router.post("/api/admin/reminders/test")
async def send_test(request: Request, body: SendReminders):
    admin(request)
    recipient_id = request.state.user["telegram_id"]
    if not recipient_id.isdigit():
        recipient_id = next(iter(workspaces.admins()), "")
    if not recipient_id:
        raise HTTPException(422, "Укажите Telegram ID администратора на сервере")
    if body.text is not None and not body.text.strip():
        raise HTTPException(422, "Введите текст уведомления")
    recipient = {"telegram_id": recipient_id, "name": request.state.user["name"], "projects": []}
    try:
        return await deliver(
            today(),
            "test:" + str(body.request_id),
            [recipient],
            body.text.strip()
            if body.text is not None
            else "Проверка уведомлений журнала работ. Бот готов отправлять напоминания о дневных отчётах.",
        )
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/api/admin/reminders/send")
async def send_now(request: Request, body: SendReminders):
    admin(request)
    if body.text is not None and not body.text.strip():
        raise HTTPException(422, "Введите текст уведомления")
    if body.audience == "selected" and not body.recipient_ids:
        raise HTTPException(422, "Выберите получателей")
    try:
        day = today()
        return await deliver(
            day,
            "manual:" + str(body.request_id),
            send_to(day, body.audience, body.recipient_ids) if body.audience else None,
            body.text.strip() if body.text is not None else None,
        )
    except ValueError as error:
        raise HTTPException(422, str(error))


async def scheduled_reminders():
    while True:
        await asyncio.sleep(30)
        try:
            config = settings()
            moment = datetime.now(MINSK_TIMEZONE)
            if (
                config.enabled
                and moment.weekday() in config.weekdays
                and moment.strftime("%H:%M") >= config.time
            ):
                await deliver(moment.date().isoformat(), "scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            continue
