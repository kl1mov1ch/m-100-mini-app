import json
import os
from decimal import ROUND_HALF_UP, Decimal

from . import bitrix, matcher, store, workspaces
from .clock import today


def ai_settings(db):
    return {
        **{k: store.setting(db, k) for k in ("llm_api_key", "llm_base_url", "llm_model")},
        **workspaces.shared(),
    }


def payroll(db, lines, count):
    rates = {
        row["id"]: Decimal(str(row["rate"])) for row in db.execute("SELECT id,rate FROM positions")
    }
    total = sum(
        (Decimal(str(l["quantity"])) * rates.get(l["item_id"], Decimal(0)) for l in lines),
        Decimal(0),
    ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    cents = int(total * 100)
    base = cents // count
    extra = cents % count
    return {
        "amount": float(total),
        "crew_count": count,
        "per_person": base / 100,
        "extra_people": extra,
        "extra_per_person": (base + 1) / 100,
        "currency": "BYN",
    }


def get_report(db, day):
    row = db.execute("SELECT * FROM reports WHERE date=?", (day,)).fetchone()
    base = (
        dict(row)
        if row
        else {
            "date": day,
            "revision": 0,
            "text": "",
            "sync_status": "imported"
            if db.execute("SELECT 1 FROM entries WHERE date=?", (day,)).fetchone()
            else "local",
            "crew_count": 1,
            "sync_error": "",
            "author_id": "",
        }
    )
    lines = [
        dict(r)
        for r in db.execute(
            "SELECT item_id,quantity FROM entries WHERE date=? ORDER BY item_id", (day,)
        )
    ]
    return {**base, "lines": lines, "payroll": payroll(db, lines, base["crew_count"])}


def history(db):
    result = []
    for row in db.execute("SELECT DISTINCT date FROM entries ORDER BY date DESC").fetchall():
        r = get_report(db, row[0])
        result.append(
            {
                "date": row[0],
                "positions": len(r["lines"]),
                **r["payroll"],
                "revision": r["revision"],
                "sync_status": r["sync_status"],
                "sync_error": r["sync_error"],
                "updated_at": r.get("updated_at"),
                "crew_count": r["crew_count"] if r["revision"] else None,
            }
        )
    return result


def safe_config(db):
    return {
        "today": today(),
        "mode": os.getenv("APP_ENV", "development"),
        "currency": "BYN",
        "llm": bool(matcher.provider(ai_settings(db))["key"]),
        "source": store.setting(db, "source", "excel"),
        "source_name": store.setting(db, "source_name", "Смета работ"),
        "public_url": store.setting(db, "public_url", bitrix.PUBLIC_URL),
        "file_id": int(store.setting(db, "file_id", "0")),
        "has_webhook": bool(store.setting(db, "webhook")),
        "last_import": store.setting(db, "last_import"),
        "pending_import": bool(store.setting(db, "pending_import_token")),
        "connection_check": json.loads(store.setting(db, "connection_check", "null")),
        "detail_url": store.setting(db, "table_detail_url"),
    }


def project_summary(p, selected_date=None):
    with store.connect(p["db_path"]) as db:
        rows = history(db)
        current = next((r for r in rows if r["date"] == (selected_date or today())), None)
        return {
            **workspaces.public_project(p),
            "positions": db.execute("SELECT count(*) FROM positions").fetchone()[0],
            "today_amount": current["amount"] if current else 0,
            "today_crew": current["crew_count"] if current else None,
            "today_per_person": current["per_person"] if current else 0,
            "total_amount": round(sum(r["amount"] for r in rows), 2),
            "work_dates": [row["date"] for row in rows if row["positions"] > 0],
            "pending": db.execute(
                "SELECT count(*) FROM reports WHERE sync_status!='synced'"
            ).fetchone()[0],
            "last_change": db.execute("SELECT max(updated_at) FROM reports").fetchone()[0],
            "connected": bool(store.setting(db, "webhook")),
            "source": store.setting(db, "source", "excel"),
            "table": {
                "name": store.setting(db, "source_name", "Смета работ"),
                "read_connected": store.setting(db, "source") == "bitrix",
                "write_connected": bool(store.setting(db, "webhook"))
                and store.setting(db, "source") == "bitrix",
                "pending_review": bool(store.setting(db, "pending_import_token")),
                "last_import": store.setting(db, "last_import"),
            },
        }


def report_changes(before, body, ps):
    old = {l["item_id"]: l["quantity"] for l in before["lines"]}
    new = {l.item_id: l.quantity for l in body.lines}
    rows = [
        {
            "item_id": ident,
            "name": ps[ident]["name"],
            "unit": ps[ident]["unit"],
            "before": old.get(ident, 0),
            "after": new.get(ident, 0),
        }
        for ident in sorted(set(old) | set(new))
        if old.get(ident, 0) != new.get(ident, 0)
    ]
    return {
        "lines": rows,
        "crew_before": before["crew_count"],
        "crew_after": body.crew_count,
    }
