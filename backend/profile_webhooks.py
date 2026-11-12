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
    ident = uuid.uuid5(uuid.NAMESPACE_URL, owner_prefix(owner_id) + url).hex
    item = {"id": ident, "name": name.strip() or portal, "portal": portal, "url": url}
    with workspaces.registry() as db:
        db.execute(
            "INSERT INTO shared_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
            (owner_prefix(owner_id) + ident, json.dumps(item, ensure_ascii=False)),
        )
        row = db.execute(
            "SELECT value FROM shared_settings WHERE key=?", (owner_prefix(owner_id) + ident,)
        ).fetchone()
    return public_webhook(json.loads(row["value"]))


def webhook_url(owner_id, ident):
    with workspaces.registry() as db:
        row = db.execute(
            "SELECT value FROM shared_settings WHERE key=?", (owner_prefix(owner_id) + ident,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Вебхук не найден в вашем профиле")
    return json.loads(row["value"])["url"]
