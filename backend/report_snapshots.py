import json

from fastapi import HTTPException

from .clock import now
from .reporting import payroll


def original_report(database, day):
    snapshot = database.execute("SELECT payload FROM day_snapshots WHERE date=?", (day,)).fetchone()
    if snapshot:
        return json.loads(snapshot[0])
    for event in database.execute("SELECT payload FROM audit WHERE date=? ORDER BY id", (day,)):
        before = json.loads(event[0]).get("before", {})
        if "lines" in before and "crew_count" in before:
            return before
    return None


def remember_start(database, before):
    original = original_report(database, before["date"]) or before
    database.execute(
        "INSERT INTO day_snapshots(date,payload,created_at) VALUES(?,?,?) ON CONFLICT(date) DO NOTHING",
        (before["date"], json.dumps(original, ensure_ascii=False), now()),
    )


def restore_target(database, day):
    original = original_report(database, day)
    if original is None:
        raise HTTPException(
            409,
            "Для этого дня исходный снимок не сохранился. Можно изменить объёмы вручную: приложение пересчитает разницу и покажет её перед подтверждением.",
        )
    positions = {row[0] for row in database.execute("SELECT id FROM positions")}
    if any(line["item_id"] not in positions for line in original["lines"]):
        raise HTTPException(
            409,
            "В исходном отчёте есть изменённые строки. Сначала обновите смету и сопоставьте работы в приложении.",
        )
    return {**original, "payroll": payroll(database, original["lines"], original["crew_count"])}
