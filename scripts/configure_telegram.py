import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.runtime import configure_runtime


async def configure_bot(url=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("Сохраните токен бота в .env или TELEGRAM_BOT_TOKEN_FILE")
    async with httpx.AsyncClient(
        timeout=20, proxy=os.getenv("TELEGRAM_PROXY_URL") or None
    ) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/getMe")
        payload = response.json()
        if not payload.get("ok"):
            raise ValueError("Telegram отклонил токен бота")
        username = payload["result"]["username"]
        print(f"Бот проверен: @{username}")
        if not url:
            return
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Нужен публичный HTTPS-адрес Mini App")
        health = await client.get(url.rstrip("/") + "/healthz")
        if health.status_code != 200 or health.json().get("status") != "ok":
            raise ValueError("Сначала запустите приложение на указанном HTTPS-адресе")
        response = await client.post(
            f"https://api.telegram.org/bot{token}/setChatMenuButton",
            json={
                "menu_button": {"type": "web_app", "text": "Журнал работ", "web_app": {"url": url}}
            },
        )
        if not response.json().get("ok"):
            raise ValueError("Не удалось установить кнопку Mini App")
        print(f"Кнопка Mini App настроена: https://t.me/{username}")


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--url")
    options = arguments.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    configure_runtime()
    try:
        asyncio.run(configure_bot(options.url))
    except (httpx.HTTPError, ValueError, KeyError):
        raise SystemExit("Не удалось настроить Telegram. Проверьте токен, сеть и HTTPS-адрес.")


if __name__ == "__main__":
    main()
