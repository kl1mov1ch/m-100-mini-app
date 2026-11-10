import json
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException

from .. import bitrix, store, tables
from ..clock import now
from ..reporting import safe_config
from ..schemas import Connection

router = APIRouter()


@router.post("/api/bitrix/check")
async def check_connection():
    with store.connect() as database:
        webhook = store.setting(database, "webhook")
        public_url = store.setting(database, "public_url", bitrix.PUBLIC_URL)
        file_id = int(store.setting(database, "file_id", "0"))
        mappings = json.loads(store.setting(database, "sheet_mappings", "null"))
    try:
        if webhook:
            content, metadata = await bitrix.download_rest(webhook, file_id)
            name = metadata["NAME"]
            detail_url = metadata.get("DETAIL_URL") or public_url
        else:
            content, metadata = await bitrix.fetch_public(public_url)
            name = metadata["name"]
            detail_url = public_url
        if not mappings:
            mappings, _ = tables.discover(content)
        parsed = tables.extract(content, mappings)
        problems = [warning for warning in parsed["warnings"] if warning.get("severity") != "info"]
        result = {
            "reachable": True,
            "structure_valid": True,
            "checked_at": now(),
            "name": name,
            "positions": len(parsed["positions"]),
            "sheets": len(mappings),
            "issues": problems,
            "write_configured": bool(webhook),
            "message": "Таблица отвечает"
            if not problems
            else "Таблица отвечает, есть замечания к данным",
        }
        with store.connect() as database:
            store.set_setting(database, "connection_check", json.dumps(result, ensure_ascii=False))
            if detail_url and urlparse(detail_url).scheme == "https":
                store.set_setting(database, "table_detail_url", detail_url)
        return result
    except (ValueError, httpx.HTTPError, KeyError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Битрикс24 не ответил. Проверьте ссылку и доступ к файлу."
        )
        result = {
            "reachable": False,
            "checked_at": now(),
            "issues": [],
            "message": message,
            "write_configured": bool(webhook),
        }
        with store.connect() as database:
            store.set_setting(database, "connection_check", json.dumps(result, ensure_ascii=False))
        return result


@router.post("/api/bitrix/connection")
async def connection(body: Connection):
    try:
        file_id = body.file_id
        if body.public_url:
            bitrix.validate_public(body.public_url)
            if not file_id:
                _, metadata = await bitrix.fetch_public(body.public_url)
                file_id = int(metadata["file_id"])
        if body.webhook:
            if not file_id:
                raise ValueError("Укажите ID файла на Диске")
            await bitrix.download_rest(body.webhook, file_id)
        with store.connect() as db:
            if (
                store.setting(db, "source") == "bitrix"
                and int(store.setting(db, "file_id", "0")) != file_id
            ):
                raise HTTPException(409, "Для другого файла добавьте отдельный объект")
            for k, v in [
                ("public_url", body.public_url),
                ("file_id", str(file_id or 0)),
            ]:
                store.set_setting(db, k, v)
            if body.webhook:
                store.set_setting(db, "webhook", body.webhook)
            return safe_config(db)
    except (ValueError, httpx.HTTPError, KeyError):
        raise HTTPException(
            400, "Не удалось подключиться. Проверьте вебхук, ID файла и право «Диск»."
        )
