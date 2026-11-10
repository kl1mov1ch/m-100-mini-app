import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DATABASE = ContextVar("current_database", default=None)


def base_path():
    return Path(os.getenv("APP_DATABASE", str(ROOT / "data/m100.sqlite3"))).resolve()


@contextmanager
def connect(path=None):
    path = Path(path or CURRENT_DATABASE.get() or base_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init(path=None, seed=True):
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,name TEXT,section TEXT,unit TEXT,planned REAL,rate REAL,source_row INTEGER);
        CREATE TABLE IF NOT EXISTS entries(item_id TEXT REFERENCES positions(id),date TEXT,quantity REAL,PRIMARY KEY(item_id,date));
        CREATE TABLE IF NOT EXISTS reports(date TEXT PRIMARY KEY,revision INTEGER DEFAULT 0,text TEXT,updated_at TEXT,sync_status TEXT DEFAULT 'local');
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,date TEXT,payload TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        """)
        columns = {r["name"] for r in db.execute("PRAGMA table_info(reports)")}
        for column, definition in [
            ("crew_count", "INTEGER NOT NULL DEFAULT 1"),
            ("sync_error", "TEXT NOT NULL DEFAULT ''"),
            ("author_id", "TEXT NOT NULL DEFAULT ''"),
            ("sync_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("retry_at", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if column not in columns:
                db.execute(f"ALTER TABLE reports ADD COLUMN {column} {definition}")
        position_columns = {r["name"] for r in db.execute("PRAGMA table_info(positions)")}
        for column, definition in [
            ("source_sheet", "TEXT NOT NULL DEFAULT ''"),
            ("baseline", "REAL NOT NULL DEFAULT 0"),
        ]:
            if column not in position_columns:
                db.execute(f"ALTER TABLE positions ADD COLUMN {column} {definition}")
        if seed and not db.execute("SELECT 1 FROM positions LIMIT 1").fetchone():
            seed_path = Path(os.getenv("APP_SEED_FILE", str(ROOT / "data/seed.json")))
            if not seed_path.exists():
                return
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            for p in seed["positions"]:
                insert_position(db, p)
            for e in seed["entries"]:
                db.execute(
                    "INSERT INTO entries VALUES(:item_id,:date,:quantity) ON CONFLICT(item_id,date) DO UPDATE SET quantity=quantity+excluded.quantity",
                    e,
                )


def positions(db):
    return [
        dict(r)
        for r in db.execute("""SELECT p.*,round(p.baseline+COALESCE(sum(e.quantity),0),4) completed,
        round(p.planned-p.baseline-COALESCE(sum(e.quantity),0),4) remaining FROM positions p
        LEFT JOIN entries e ON p.id=e.item_id GROUP BY p.id ORDER BY p.source_row""")
    ]


def insert_position(db, p):
    db.execute(
        "INSERT INTO positions(id,name,section,unit,planned,rate,source_row,source_sheet,baseline) VALUES(:id,:name,:section,:unit,:planned,:rate,:source_row,:source_sheet,:baseline)",
        {
            **p,
            "source_sheet": p.get("source_sheet", ""),
            "baseline": p.get("baseline", 0),
        },
    )


def setting(db, key, default=""):
    r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(db, key, value):
    db.execute(
        "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
