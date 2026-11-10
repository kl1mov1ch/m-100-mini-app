"""Access registry. Each object has a separate database, guarded before selection."""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from . import store


@contextmanager
def registry():
    path = Path(os.getenv("APP_REGISTRY", str(store.base_path().with_suffix(".registry.sqlite3"))))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def admins():
    return [s.strip() for s in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if s.strip()]


def init():
    with registry() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(telegram_id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,name TEXT NOT NULL,db_path TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shared_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        identities = admins()
        if os.getenv("APP_ENV", "development") == "development":
            identities = ["local-admin", *identities]
        for ident in identities:
            db.execute(
                "INSERT INTO users VALUES(?,?,'admin',1) ON CONFLICT(telegram_id) DO UPDATE SET role='admin',enabled=1",
                (ident, "Администратор"),
            )
        if (
            not db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
            and identities
            and os.getenv("APP_ENV", "development") == "development"
        ):
            db.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?)",
                (
                    "default",
                    identities[0],
                    "Детский сад",
                    str(store.base_path()),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        database_paths = [row["db_path"] for row in db.execute("SELECT db_path FROM projects")]
    for database_path in database_paths:
        store.init(database_path, seed=False)


def user(ident):
    with registry() as db:
        row = db.execute("SELECT * FROM users WHERE telegram_id=?", (str(ident),)).fetchone()
    if not row or not row["enabled"]:
        raise HTTPException(403, "Доступ не предоставлен. Обратитесь к администратору.")
    return dict(row)


def visible(user):
    with registry() as db:
        query = (
            "SELECT p.*,u.name owner_name FROM projects p JOIN users u ON p.owner_id=u.telegram_id"
        )
        rows = db.execute(
            query
            + ("" if user["role"] == "admin" else " WHERE p.owner_id=?")
            + " ORDER BY p.created_at DESC",
            () if user["role"] == "admin" else (user["telegram_id"],),
        ).fetchall()
        return [dict(r) for r in rows]


def project(user, ident=None):
    rows = visible(user)
    selected = (
        next((p for p in rows if p["id"] == ident), None) if ident else next(iter(rows), None)
    )
    if not selected:
        raise HTTPException(
            403 if ident else 404,
            "Объект недоступен" if ident else "Добавьте первый объект",
        )
    return selected


def public_project(p):
    return {k: p[k] for k in ("id", "name", "owner_id", "owner_name", "created_at") if k in p}


def add_project(current_user, name, owner_id=None, sample=False):
    owner_id = owner_id or current_user["telegram_id"]
    if current_user["role"] != "admin" and owner_id != current_user["telegram_id"]:
        raise HTTPException(403, "Можно создавать объекты только в своём кабинете")
    user(owner_id)
    ident = uuid.uuid4().hex
    path = store.base_path().parent / "objects" / f"{ident}.sqlite3"
    store.init(path, seed=sample)
    with registry() as db:
        db.execute(
            "INSERT INTO projects VALUES(?,?,?,?,?)",
            (ident, owner_id, name, str(path), datetime.now(timezone.utc).isoformat()),
        )
    return project(current_user, ident)


def shared():
    with registry() as db:
        return {r["key"]: r["value"] for r in db.execute("SELECT * FROM shared_settings")}


def set_shared(values):
    with registry() as db:
        for k, v in values.items():
            db.execute(
                "INSERT INTO shared_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, v),
            )
