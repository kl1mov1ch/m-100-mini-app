import json

from fastapi import HTTPException

from . import store
from .bitrix_refresh import remote_positions


def position_detail(db, ident):
    position = next((row for row in store.positions(db) if row["id"] == ident), None)
    if position is None:
        raise HTTPException(404, "Работа отсутствует в смете")
    bitrix = remote_positions(db).get(ident)
    return {
        **position,
        "bitrix": bitrix,
        "hidden": ident in store.hidden_positions(db),
        "linked_work_id": store.position_links(db).get(ident),
    }


def has_overrun(position):
    remote = position["bitrix"]
    return position["remaining"] < 0 or (remote is not None and remote["remaining"] < 0)


def position_history(db, ident, limit):
    events = []
    for row in db.execute("SELECT date,payload,created_at FROM audit ORDER BY id DESC"):
        payload = json.loads(row["payload"])
        common = {"created_at": row["created_at"], "actor": payload.get("actor_name")}
        for change in (payload.get("changes") or {}).get("lines", []):
            if change["item_id"] == ident:
                events.append(
                    {
                        **common,
                        "kind": "report_restore"
                        if payload.get("action") == "restore_day"
                        else "report",
                        "date": row["date"],
                        "before": change["before"],
                        "after": change["after"],
                    }
                )
        update = payload.get("position_updates", {}).get(ident)
        if update:
            events.append(
                {
                    **common,
                    "kind": "bitrix_values"
                    if payload.get("action") == "bitrix_read"
                    else "estimate",
                    "date": row["date"],
                    "values": update,
                }
            )
        for change in payload.get("position_days", []):
            if change["item_id"] == ident:
                events.append(
                    {
                        **common,
                        "kind": "bitrix_day",
                        "date": change["date"],
                        "before": change["before"],
                        "after": change["after"],
                    }
                )
        if payload.get("position_id") == ident:
            action = payload["action"].removeprefix("catalogue_position_")
            events.append(
                {**common, "kind": action, "date": row["date"], "work": payload.get("work_name")}
            )
        if len(events) >= limit:
            break
    return {
        "events": events[:limit],
        "days": [
            dict(row)
            for row in db.execute(
                "SELECT e.date,e.quantity,r.sync_status FROM entries e "
                "LEFT JOIN reports r ON r.date=e.date WHERE e.item_id=? ORDER BY e.date DESC LIMIT ?",
                (ident, limit),
            )
        ],
    }
