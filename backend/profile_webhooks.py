import json
import uuid
from urllib.parse import urlparse

from fastapi import HTTPException

from . import bitrix, workspaces

PREFIX = "profile_disk_webhook:"


def owner_prefix(owner_id):
    return f"{PREFIX}{owner_id}:"


def public_webhook(webhook):
    return {key: webhook[key] for key in ("id", "name", "portal")}


def list_webhooks(owner_id):
    with workspaces.registry() as db:
        rows = db.execute(
            "SELECT value FROM shared_settings WHERE key LIKE ?", (owner_prefix(owner_id) + "%",)
        )
        items = [public_webhook(json.loads(row["value"])) for row in rows]
    return sorted(items, key=lambda item: (item["name"].casefold(), item["portal"], item["id"]))


def save_webhook(owner_id, name, url):
    url = bitrix.validate_webhook(url.strip())
    portal = urlparse(url).hostname
    ident = uuid.uuid4().hex
    item = {"id": ident, "name": name.strip() or portal, "portal": portal, "url": url}
    with workspaces.registry() as db:
        existing = db.execute(
            "SELECT value FROM shared_settings WHERE key LIKE ?", (owner_prefix(owner_id) + "%",)
        ).fetchall()
        for row in existing:
            item_saved = json.loads(row["value"])
            if item_saved["url"] == url:
                return public_webhook(item_saved)
        db.execute(
            "INSERT INTO shared_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
            (owner_prefix(owner_id) + ident, json.dumps(item, ensure_ascii=False)),
        )
        row = db.execute(
            "SELECT value FROM shared_settings WHERE key=?", (owner_prefix(owner_id) + ident,)
        ).fetchone()
    return public_webhook(json.loads(row["value"]))


def update_webhook(owner_id, ident, name, url):
    with workspaces.registry() as db:
        key = owner_prefix(owner_id) + ident
        row = db.execute("SELECT value FROM shared_settings WHERE key=?", (key,)).fetchone()
        if row is None:
            raise HTTPException(404, "Вебхук не найден в вашем профиле")
        item = json.loads(row["value"])
        if url.strip():
            item["url"] = bitrix.validate_webhook(url.strip())
        item["portal"] = urlparse(item["url"]).hostname
        item["name"] = name.strip() or item["portal"]
        others = db.execute(
            "SELECT key,value FROM shared_settings WHERE key LIKE ? AND key<>?",
            (owner_prefix(owner_id) + "%", key),
        ).fetchall()
        if any(json.loads(other["value"])["url"] == item["url"] for other in others):
            raise HTTPException(409, "Такой вебхук уже сохранён. Выберите его из списка.")
        db.execute(
            "UPDATE shared_settings SET value=? WHERE key=?",
            (json.dumps(item, ensure_ascii=False), key),
        )
    return public_webhook(item)


def delete_webhook(owner_id, ident):
    with workspaces.registry() as db:
        result = db.execute(
            "DELETE FROM shared_settings WHERE key=?", (owner_prefix(owner_id) + ident,)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Вебхук не найден в вашем профиле")
    return {"deleted": True}


def webhook_url(owner_id, ident):
    with workspaces.registry() as db:
        row = db.execute(
            "SELECT value FROM shared_settings WHERE key=?", (owner_prefix(owner_id) + ident,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Вебхук не найден в вашем профиле")
    return json.loads(row["value"])["url"]
