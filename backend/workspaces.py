"""Access registry. Each object has a separate database, guarded before selection."""

import asyncio
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from weakref import WeakValueDictionary

from fastapi import HTTPException

from . import postgres, store
from .naming import unique_project_name

PROJECT_LOCKS = WeakValueDictionary()


def mutation_lock(ident):
    return PROJECT_LOCKS.setdefault(ident, asyncio.Lock())


def exists(ident):
    with registry() as db:
        return db.execute("SELECT 1 FROM projects WHERE id=?", (ident,)).fetchone() is not None


def delete_project(project):
    ident = project["id"]
    relations = ("entries", "positions", "reports", "audit", "settings", "day_snapshots")
    if postgres.enabled():
        with store.connect(project["db_path"]) as db:
            db.execute("BEGIN IMMEDIATE")
            for relation in relations:
                db.execute(f"DELETE FROM {relation}")
            db.execute("DELETE FROM registry.projects WHERE id=?", (ident,))
            if ident == "default":
                db.execute(
                    "INSERT INTO registry.shared_settings(key,value) VALUES('default_object_removed','1') "
                    "ON CONFLICT DO NOTHING"
                )
        return
    with registry() as db:
        db.execute("ATTACH DATABASE ? AS object_data", (project["db_path"],))
        db.execute("BEGIN IMMEDIATE")
        for relation in relations:
            db.execute(f"DELETE FROM object_data.{relation}")
        db.execute("DELETE FROM projects WHERE id=?", (ident,))
        if ident == "default":
            db.execute(
                "INSERT INTO shared_settings(key,value) VALUES('default_object_removed','1') "
                "ON CONFLICT(key) DO NOTHING"
            )


@contextmanager
def registry():
    if postgres.enabled():
        with postgres.connect() as database:
            yield database
        return
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
        if not postgres.enabled():
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users(telegram_id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,name TEXT NOT NULL,db_path TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shared_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminder_deliveries(telegram_id TEXT, day TEXT, run_key TEXT, status TEXT, error TEXT, created_at TEXT, PRIMARY KEY(telegram_id,day,run_key));
            CREATE TABLE IF NOT EXISTS profile_avatars(telegram_id TEXT PRIMARY KEY,content BLOB NOT NULL,mime TEXT NOT NULL,checked_at INTEGER NOT NULL);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            for column, definition in (
                ("avatar_url", "TEXT NOT NULL DEFAULT ''"),
                ("username", "TEXT NOT NULL DEFAULT ''"),
                ("custom_name", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in columns:
                    db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
        identities = admins()
        if os.getenv("APP_ENV", "development") == "development":
            identities = ["local-admin", *identities]
        for ident in identities:
            db.execute(
                "INSERT INTO users(telegram_id,name,role,enabled) VALUES(?,?,'admin',1) ON CONFLICT(telegram_id) DO UPDATE SET role='admin',enabled=1",
                (ident, "Администратор"),
            )
        if (
            not db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
            and not db.execute(
                "SELECT 1 FROM shared_settings WHERE key='default_object_removed'"
            ).fetchone()
            and identities
            and os.getenv("APP_ENV", "development") == "development"
        ):
            db.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?)",
                (
                    "default",
                    identities[0],
                    "Детский сад",
                    "project:default" if postgres.enabled() else str(store.base_path()),
                    datetime.now(UTC).isoformat(),
                ),
            )
            if postgres.enabled():
                db.select_project("default")
                store.seed_database(db)
        database_paths = (
            []
            if postgres.enabled()
            else [row["db_path"] for row in db.execute("SELECT db_path FROM projects")]
        )
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
    path = f"project:{ident}"
    if not postgres.enabled():
        path = str(store.base_path().parent / "objects" / f"{ident}.sqlite3")
        store.init(path, seed=sample)
    with registry() as db:
        if postgres.enabled():
            from sqlalchemy import select

            from .orm_models import Project, User

            db.session.scalar(select(User).where(User.telegram_id == owner_id).with_for_update())
            existing = list(
                db.session.scalars(select(Project.name).where(Project.owner_id == owner_id))
            )
        else:
            db.execute("BEGIN IMMEDIATE")
            existing = [
                row[0]
                for row in db.execute("SELECT name FROM projects WHERE owner_id=?", (owner_id,))
            ]
        name = unique_project_name(name, existing)
        db.execute(
            "INSERT INTO projects VALUES(?,?,?,?,?)",
            (ident, owner_id, name, str(path), datetime.now(UTC).isoformat()),
        )
        if postgres.enabled() and sample:
            db.select_project(ident)
            store.seed_database(db)
    return project(current_user, ident)


def shared():
    with registry() as db:
        return {
            r["key"]: r["value"]
            for r in db.execute(
                "SELECT * FROM shared_settings WHERE key NOT LIKE 'profile_disk_webhook:%'"
            )
        }


def set_shared(values):
    with registry() as db:
        for k, v in values.items():
            db.execute(
                "INSERT INTO shared_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, v),
            )
