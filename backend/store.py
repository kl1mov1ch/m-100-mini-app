import json
import os
import sqlite3
from collections import Counter
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
        CREATE TABLE IF NOT EXISTS day_snapshots(date TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
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
        db.executescript("""
        CREATE INDEX IF NOT EXISTS entries_by_date ON entries(date,item_id);
        CREATE INDEX IF NOT EXISTS audit_by_date ON audit(date,id);
        CREATE INDEX IF NOT EXISTS reports_for_retry ON reports(sync_status,retry_at,date);
        """)
        position_columns = {r["name"] for r in db.execute("PRAGMA table_info(positions)")}
        for column, definition in [
            ("source_sheet", "TEXT NOT NULL DEFAULT ''"),
            ("baseline", "REAL NOT NULL DEFAULT 0"),
        ]:
            if column not in position_columns:
                db.execute(f"ALTER TABLE positions ADD COLUMN {column} {definition}")
        if seed:
            seed_database(db)


def seed_database(database):
    if setting(database, "seed_initialized"):
        return
    set_setting(database, "seed_initialized", "1")
    if database.execute("SELECT 1 FROM positions LIMIT 1").fetchone():
        return
    seed_path = Path(os.getenv("APP_SEED_FILE", str(ROOT / "data/seed.json")))
    if not seed_path.exists():
        return
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    for position in seed["positions"]:
        insert_position(database, position)
    for entry in seed["entries"]:
        database.execute(
            "INSERT INTO entries(item_id,date,quantity) VALUES(:item_id,:date,:quantity) ON CONFLICT(item_id,date) DO UPDATE SET quantity=entries.quantity+excluded.quantity",
            entry,
        )


def positions(db):
    return [
        dict(r)
        for r in db.execute("""SELECT p.*,round(p.baseline+COALESCE(sum(e.quantity),0),4) completed,
        round(p.planned-p.baseline-COALESCE(sum(e.quantity),0),4) remaining FROM positions p
        LEFT JOIN entries e ON p.id=e.item_id GROUP BY p.id ORDER BY p.source_row""")
    ]


def hidden_positions(db):
    return json.loads(setting(db, "hidden_positions", "{}"))


def position_links(db):
    return json.loads(setting(db, "position_links", "{}"))


def position_identity(position):
    return [str(position[key] or "").strip().casefold() for key in ("name", "unit", "section")]


def restore_hidden_positions(db, incoming):
    hidden = hidden_positions(db)
    if not hidden:
        return
    restored = {}
    identities = {position["id"]: position_identity(position) for position in incoming}
    counts = Counter(tuple(identity) for identity in identities.values())
    previously_hidden = {tuple(identity) for identity in hidden.values()}
    for ident, identity in identities.items():
        if hidden.get(ident) == identity or (
            tuple(identity) in previously_hidden and counts[tuple(identity)] == 1
        ):
            restored[ident] = identity
    set_setting(db, "hidden_positions", json.dumps(restored, ensure_ascii=False))


def selectable_positions(db):
    hidden = hidden_positions(db)
    return [position for position in positions(db) if position["id"] not in hidden]


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
