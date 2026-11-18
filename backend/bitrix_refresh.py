import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta
from weakref import WeakValueDictionary
from zipfile import BadZipFile

import httpx
from openpyxl.utils.exceptions import InvalidFileException

from . import bitrix, store, tables, workbook_revision, workspaces
from .bitrix_review import compare_values, layout_issue, report_issue, warning_issue
from .clock import now
from .synchronization import table_lock

READ_LOCKS = WeakValueDictionary()
CONNECTION_KEYS = (
    "source",
    "webhook",
    "file_id",
    "public_url",
    "last_import",
    "sheet_mappings",
    "remote_days",
)


def freshness(db):
    return json.loads(store.setting(db, "bitrix_read_status", "null"))


def remote_positions(db):
    return json.loads(store.setting(db, "bitrix_read_positions", "{}"))


def review_issues(db):
    return json.loads(store.setting(db, "bitrix_read_issues", "null"))


def connection(db):
    return tuple(store.setting(db, key) for key in CONNECTION_KEYS)


def entries_by_day(entries):
    result = defaultdict(dict)
    for entry in entries:
        day = result[entry["date"]]
        ident = entry["item_id"]
        day[ident] = day.get(ident, 0) + entry["quantity"]
    return dict(result)


def match_positions(local, incoming):
    rows = defaultdict(list)
    for position in incoming:
        rows[position["source_row"]].append(position)
    matched = {}
    journal_ids = {
        position["id"]: position for position in incoming if position.get("journal_position")
    }
    for position in local:
        if position["id"] in journal_ids:
            matched[position["id"]] = (position["id"], journal_ids[position["id"]])
            continue
        same = [
            candidate
            for candidate in rows[position["source_row"]]
            if tables.text(candidate["name"]) == tables.text(position["name"])
            and candidate["unit"] == position["unit"]
            and (
                not position["source_sheet"]
                or candidate["source_sheet"] == position["source_sheet"]
            )
        ]
        if len(same) == 1:
            matched[same[0]["id"]] = (position["id"], same[0])
    return matched


def apply_read(db, extracted):
    local = store.positions(db)
    matched = match_positions(local, extracted["positions"])
    remote = entries_by_day(
        {**entry, "item_id": matched[entry["item_id"]][0]}
        for entry in extracted["entries"]
        if entry["item_id"] in matched
    )
    totals = defaultdict(float)
    for rows in remote.values():
        for ident, quantity in rows.items():
            totals[ident] += quantity
    snapshot = {}
    for ident, position in matched.values():
        completed = None if position.get("journal_position") else position["workbook_completed"]
        if completed is None:
            completed = position["baseline"] + totals[ident]
        remaining = None if position.get("journal_position") else position["workbook_remaining"]
        snapshot[ident] = {
            "planned": position["planned"],
            "rate": position["rate"],
            "completed": round(completed, 4),
            "remaining": round(
                position["planned"] - completed if remaining is None else remaining, 4
            ),
        }
    warnings = [warning for warning in extracted["warnings"] if warning.get("severity") != "info"]
    deleted = store.deleted_positions(db)
    missing = [position for position in local if position["id"] not in snapshot]
    layout_changed = any(position["id"] not in deleted for position in missing) or len(
        matched
    ) != len(extracted["positions"])
    relevant_warnings = [
        warning
        for warning in warnings
        if warning.get("field")
        in ("Плановый объём", "Расценка", "Единица измерения", "Дневной объём")
        or warning.get("duplicates")
        or ":missing:" in warning["id"]
        or warning["id"].endswith(":values")
    ]
    invalid_fields = defaultdict(set)
    invalid_days = set()
    duplicate_days = set()
    for warning in relevant_warnings:
        row = (warning.get("sheet"), warning.get("row"))
        invalid_fields[row].add(warning.get("field"))
        if warning.get("date"):
            invalid_days.update(
                (row[0], affected, warning["date"])
                for affected in warning.get("affected_rows", [row[1]])
            )
        duplicate_days.update((row[0], item["date"]) for item in warning.get("duplicates", []))
    issues = [warning_issue(warning) for warning in relevant_warnings]
    appearance = extracted.get("appearance")
    if appearance is not None:
        previous_colors = json.loads(store.setting(db, "bitrix_appearance", "null"))
        store.set_setting(
            db, "bitrix_appearance_observed", json.dumps(appearance, ensure_ascii=False)
        )
        if previous_colors is None:
            store.set_setting(db, "bitrix_appearance", json.dumps(appearance, ensure_ascii=False))
        elif previous_colors != appearance:
            locations = sorted(
                key
                for key in previous_colors.keys() | appearance.keys()
                if previous_colors.get(key) != appearance.get(key)
            )
            issues.append(
                {
                    "kind": "appearance",
                    "title": "Изменена заливка ячеек",
                    "sheet": locations[0],
                    "advice": "Подтвердите оформление, если оно внесено намеренно.",
                    "version": workbook_revision.appearance_version(appearance),
                }
            )
    if layout_changed or missing:
        issues.extend(
            layout_issue(position, True)
            for position in extracted["positions"]
            if position["id"] not in matched
        )
        for position in missing:
            issue = layout_issue(position, False)
            if position["id"] in deleted:
                issue.update(
                    title="Работа удалена из Битрикс24",
                    advice="Ранее подтверждённые объёмы сохранены в истории.",
                )
            issues.append(issue)
    remote_by_id = dict(matched.values())
    previous = remote_positions(db)
    seen = json.loads(store.setting(db, "bitrix_read_days", "{}"))
    saved_days = {
        row["date"]: row["sync_status"]
        for row in db.execute("SELECT date,sync_status FROM reports")
    }
    baseline = json.loads(store.setting(db, "remote_days", "{}"))
    current = entries_by_day(
        dict(row) for row in db.execute("SELECT item_id,date,quantity FROM entries")
    )
    applied_days = []
    day_changes = []
    for day in sorted(set(remote) | set(current) | set(seen)):
        fresh = remote.get(day, {})
        before = seen.get(day, baseline.get(day, current.get(day, {})))
        for ident in (before.keys() | fresh.keys()) & snapshot.keys():
            if not bitrix.equal_quantities(
                {ident: before.get(ident, 0)}, {ident: fresh.get(ident, 0)}
            ):
                day_changes.append(
                    {
                        "item_id": ident,
                        "date": day,
                        "before": before.get(ident, 0),
                        "after": fresh.get(ident, 0),
                    }
                )
        if day in saved_days:
            if not bitrix.equal_quantities(fresh, current.get(day, {})) and (
                not bitrix.equal_quantities(fresh, baseline.get(day, {}))
                or saved_days[day] in ("synced", "error")
            ):
                local_day = current.get(day, {})
                for ident in sorted((fresh.keys() | local_day.keys()) & snapshot.keys()):
                    remote_position = remote_by_id[ident]
                    coordinates = (
                        remote_position["source_sheet"],
                        remote_position["source_row"],
                        day,
                    )
                    local_qty, remote_qty = local_day.get(ident, 0), fresh.get(ident, 0)
                    if (
                        coordinates not in invalid_days
                        and (coordinates[0], day) not in duplicate_days
                        and not bitrix.equal_quantities({ident: local_qty}, {ident: remote_qty})
                    ):
                        issues.append(
                            report_issue(
                                remote_position,
                                day,
                                local_qty,
                                remote_qty,
                                baseline.get(day, {}).get(ident, 0),
                            )
                        )
        elif (
            not layout_changed
            and not warnings
            and not bitrix.equal_quantities(fresh, current.get(day, {}))
        ):
            archived_quantities = {
                ident: quantity
                for ident, quantity in current.get(day, {}).items()
                if ident in deleted and ident not in snapshot
            }
            if bitrix.equal_quantities({**fresh, **archived_quantities}, current.get(day, {})):
                continue
            db.execute("DELETE FROM entries WHERE date=?", (day,))
            db.executemany(
                "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
                [
                    (ident, day, quantity)
                    for ident, quantity in {**fresh, **archived_quantities}.items()
                    if quantity
                ],
            )
            applied_days.append(day)
    position_updates = {}
    for position in local:
        ident = position["id"]
        if ident not in snapshot:
            continue
        before = previous.get(ident, {key: position[key] for key in snapshot[ident]})
        after = snapshot[ident]
        if before != after:
            position_updates[ident] = {"before": before, "after": after}
        remote_position = remote_by_id[ident]
        row = (remote_position["source_sheet"], remote_position["source_row"])
        issues.extend(compare_values(position, remote_position, after, invalid_fields[row]))
    if position_updates or day_changes:
        checked = now()
        db.execute(
            "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
            (
                checked[:10],
                json.dumps(
                    {
                        "action": "bitrix_read",
                        "position_updates": position_updates,
                        "position_days": day_changes,
                        "applied_days": applied_days,
                    },
                    ensure_ascii=False,
                ),
                checked,
            ),
        )
    store.set_setting(db, "bitrix_read_positions", json.dumps(snapshot))
    store.set_setting(db, "bitrix_read_days", json.dumps(remote))
    store.set_setting(db, "bitrix_read_issues", json.dumps(issues, ensure_ascii=False))
    if applied_days:
        baseline.update({day: remote.get(day, {}) for day in applied_days})
        store.set_setting(db, "remote_days", json.dumps(baseline))
    return bool(issues)


def adopt_working_catalogue(db, parsed):
    if not parsed.get("generated") or not parsed["positions"]:
        raise ValueError("Рабочий лист «Журнал работ» не найден или пуст. Отчёт сохранён.")
    blocking = next(
        (
            warning
            for warning in parsed.get("warnings", [])
            if warning.get("severity") != "info" and warning.get("field") != "Дневной объём"
        ),
        None,
    )
    if blocking:
        raise ValueError(blocking["message"])
    local = {row["id"]: row for row in store.positions(db)}
    remote = {row["id"]: row for row in parsed["positions"]}
    deleted = store.deleted_positions(db)
    missing = (local.keys() - remote.keys()) - deleted.keys()
    if missing and (
        not (local.keys() & remote.keys())
        or any(not position["journal_position"] for position in remote.values())
    ):
        raise ValueError(
            "В рабочем листе изменились строки. Не удалось подтвердить соответствие работ."
        )
    updates = {}
    for ident in local.keys() & remote.keys():
        old, new = local[ident], remote[ident]
        if old["unit"] != new["unit"]:
            raise ValueError(f"В Битрикс24 изменилась единица измерения работы «{old['name']}».")
        if not new["journal_position"] and position_identity_changed(old, new):
            raise ValueError(f"В рабочем листе не удалось подтвердить работу «{old['name']}».")
        before = {key: old[key] for key in ("name", "section", "planned", "rate")}
        after = {key: new[key] for key in before}
        if before != after:
            updates[ident] = {"before": before, "after": after}
    added = remote.keys() - local.keys()
    if not (updates or missing or added):
        raise ValueError("Рабочий лист поменялся. Не удалось однозначно сопоставить позиции.")
    timestamp = now()
    for ident in sorted(updates):
        new = updates[ident]["after"]
        db.execute(
            "UPDATE positions SET name=?,section=?,planned=?,rate=? WHERE id=?",
            (new["name"], new["section"], new["planned"], new["rate"], ident),
        )
    for ident in sorted(added):
        store.insert_position(db, remote[ident])
    deleted.update({ident: timestamp for ident in missing})
    store.set_setting(db, "deleted_positions", json.dumps(deleted))
    db.execute(
        "INSERT INTO audit(date,payload,created_at) VALUES(?,?,?)",
        (
            timestamp[:10],
            json.dumps(
                {
                    "action": "bitrix_catalogue_refresh",
                    "position_updates": updates,
                    "added": sorted(added),
                    "deleted": sorted(missing),
                },
                ensure_ascii=False,
            ),
            timestamp,
        ),
    )


def position_identity_changed(old, new):
    return tables.text(old["name"]) != tables.text(new["name"])


def extract_workbook(content, mappings):
    parsed = bitrix.read_workbook(content, mappings, generated_only=True)
    if parsed is None:
        return None
    return {
        **parsed,
        "appearance": workbook_revision.colors(content),
    }


async def refresh_project(project, max_age=90):
    ident = project["id"]
    lock = READ_LOCKS.setdefault(ident, asyncio.Lock())
    async with lock:
        with store.connect(project["db_path"]) as db:
            if store.setting(db, "journal_rebuild"):
                return freshness(db)
            expected = connection(db)
            source, webhook, file_id, url, _, raw_mappings, _ = expected
            previous = freshness(db)
            working_seen = store.setting(db, "bitrix_working_seen") == "1"
        if source != "bitrix":
            return None
        if (
            previous
            and (working_seen or previous["status"] != "review")
            and datetime.fromisoformat(now()) - datetime.fromisoformat(previous["checked_at"])
            < timedelta(
                seconds=min(max_age, 120) if previous["status"] == "unavailable" else max_age
            )
        ):
            return previous
        content = extracted = None
        workbook_issue = None
        try:
            if webhook and file_id and int(file_id):
                content, _ = await bitrix.download_rest(webhook, int(file_id))
            elif url:
                content, _ = await bitrix.fetch_public(url)
            else:
                return None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
        if content is not None:
            try:
                extracted = await asyncio.to_thread(
                    extract_workbook, content, json.loads(raw_mappings or "null")
                )
            except (InvalidFileException, BadZipFile, ValueError, KeyError, TypeError):
                workbook_issue = {
                    "kind": "layout",
                    "title": "Структуру таблицы не удалось прочитать",
                    "advice": "Откройте проверку таблицы и проверьте листы, строку заголовков и столбцы сметы.",
                }
        async with table_lock(project):
            if not workspaces.exists(ident):
                return None
            with store.connect(project["db_path"]) as db:
                db.execute("BEGIN IMMEDIATE")
                if connection(db) != expected or store.setting(db, "journal_rebuild"):
                    return freshness(db)
                checked_at = now()
                if (
                    working_seen
                    and content is not None
                    and extracted is None
                    and not workbook_issue
                ):
                    workbook_issue = {
                        "kind": "layout",
                        "title": "Рабочий лист «Журнал работ» удалён или изменён",
                        "advice": "Проверьте рабочие листы в Битрикс24.",
                    }
                if workbook_issue and working_seen:
                    store.set_setting(
                        db, "bitrix_read_issues", json.dumps([workbook_issue], ensure_ascii=False)
                    )
                    status = "review"
                elif content is None:
                    store.set_setting(db, "bitrix_read_issues", "[]")
                    status = "unavailable"
                elif extracted is None:
                    store.set_setting(db, "bitrix_read_issues", "[]")
                    store.set_setting(db, "bitrix_read_positions", "{}")
                    store.set_setting(db, "bitrix_read_days", "{}")
                    status = "current"
                else:
                    store.set_setting(db, "bitrix_working_seen", "1")
                    status = "review" if apply_read(db, extracted) else "current"
                result = {
                    "status": status,
                    "checked_at": checked_at,
                    "updated_at": checked_at
                    if extracted is not None
                    else (previous or {}).get("updated_at"),
                }
                store.set_setting(db, "bitrix_read_status", json.dumps(result))
                return result


async def refresh_linked_tables():
    while True:
        await asyncio.sleep(300)
        with workspaces.registry() as db:
            projects = [dict(row) for row in db.execute("SELECT * FROM projects")]
        for project in projects:
            try:
                await refresh_project(project, max_age=12 * 60 * 60)
            except (httpx.HTTPError, ValueError, OSError):
                continue
