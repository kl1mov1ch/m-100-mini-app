import io
import json
from datetime import datetime, timedelta

import openpyxl

from backend import bitrix, matcher, store, tables, workspaces
from backend.clock import today
from test_workspaces import client, create, grant


def workbook(rows=None):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Монтаж"
    sheet.append(
        [
            "Наименование",
            "Ед изм",
            "План",
            "Расценка",
            "Выполненный объём",
            "Остаток объёма",
            "Выполнено в деньгах на руки",
            datetime.fromisoformat(today()),
            datetime.fromisoformat(today()) - timedelta(days=1),
        ]
    )
    for name, unit, rate in rows or [("Монтаж кабеля 3х2,5", "м", 2)]:
        sheet.append([name, unit, 100, rate, None, None, None, None, 7])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def upload(client, headers, content):
    response = client.post(
        "/api/imports/upload", files={"file": ("estimate.xlsx", content)}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def approval(preview):
    plan = preview.get("reconciliation")
    return {
        "token": preview["token"],
        "sheets": preview["sheets"],
        "acknowledged": [warning["id"] for warning in preview["warnings"]],
        "position_matches": {row["previous"]["id"]: row["selected_id"] for row in plan["rows"]}
        if plan
        else {},
        "reconciliation_acknowledged": bool(plan),
        "reconciliation_version": plan["version"] if plan else "",
    }


def imported_project(client, content):
    ident = create(client, sample=False)
    headers = {"X-Project-Id": ident}
    preview = upload(client, headers, content)
    response = client.post("/api/imports/confirm", json=approval(preview), headers=headers)
    assert response.status_code == 200, response.text
    return ident, headers


def test_repeated_edits_removal_and_day_restore_recalculate_bitrix_columns(client, monkeypatch):
    current = workbook()
    ident, headers = imported_project(client, current)
    project = workspaces.project(workspaces.user("local-admin"), ident)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "source", "bitrix")
        store.set_setting(database, "webhook", "https://test.bitrix24.by/rest/1/test/")
        store.set_setting(database, "file_id", "123")

    async def download(webhook, file_id):
        return current, {"NAME": "estimate.xlsx"}

    async def rest(webhook, method, arguments):
        import base64

        nonlocal current
        assert method == "disk.file.uploadVersion"
        current = base64.b64decode(arguments["fileContent"][1])
        return {"ID": 123}

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", rest)
    revision = 0
    for quantity in (15, 10, 4, 0, 8):
        response = client.post(
            "/api/reports",
            json={
                "date": today(),
                "revision": revision,
                "crew_count": 5,
                "lines": [{"item_id": "excel-2", "quantity": quantity}] if quantity else [],
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["sync_status"] == "synced", report
        revision = report["revision"]
        values = openpyxl.load_workbook(io.BytesIO(current), data_only=True)["Монтаж"]
        assert values["E2"].value == quantity + 7
        assert values["F2"].value == 93 - quantity
        assert values["G2"].value == (quantity + 7) * 2
        assert values["I2"].value == 7
    preview = client.get(f"/api/report/{today()}/restore-preview", headers=headers).json()
    assert preview["target"]["lines"] == []
    restored = client.post(
        f"/api/report/{today()}/restore", json={"revision": revision}, headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["lines"] == [] and restored.json()["sync_status"] == "synced"
    values = openpyxl.load_workbook(io.BytesIO(current), data_only=True)["Монтаж"]
    assert values["E2"].value == 7 and values["F2"].value == 93 and values["G2"].value == 14
    assert (
        client.get("/api/changes", headers=headers).json()[0]["payload"]["action"] == "restore_day"
    )
    assert (
        client.post(
            f"/api/report/{today()}/restore", json={"revision": revision}, headers=headers
        ).status_code
        == 409
    )
    assert client.get("/api/analytics?project_id=" + ident).json()["summary"]["worker_days"] == 0


def test_moved_rows_preserve_report_identity_and_future_table_writes(client):
    first = workbook([("Кабель 3х2,5", "м", 2), ("Медь 6,35", "м", 3)])
    ident, headers = imported_project(client, first)
    saved = client.post(
        "/api/reports",
        json={"date": today(), "revision": 0, "lines": [{"item_id": "excel-2", "quantity": 15}]},
        headers=headers,
    )
    assert saved.status_code == 200
    second = workbook([("Медь 6,35", "м", 3), ("Кабель 3х2,5", "м", 2)])
    preview = upload(client, headers, second)
    assert preview["reconciliation"]["needs_confirmation"]
    body = approval(preview)
    response = client.post("/api/imports/confirm", json=body, headers=headers)
    assert response.status_code == 200, response.text
    positions = client.get("/api/bootstrap", headers=headers).json()["positions"]
    cable = next(position for position in positions if position["name"] == "Кабель 3х2,5")
    assert cable["id"] == "excel-2" and cable["source_row"] == 3
    report = client.get(f"/api/report/{today()}", headers=headers).json()
    assert report["lines"] == [{"item_id": "excel-2", "quantity": 15}]
    project = workspaces.project(workspaces.user("local-admin"), ident)
    with store.connect(project["db_path"]) as database:
        mappings = json.loads(store.setting(database, "sheet_mappings"))
    patched = tables.patch(second, today(), report["lines"], positions, mappings)
    values = openpyxl.load_workbook(io.BytesIO(patched), data_only=True)["Монтаж"]
    assert values["H3"].value == 15 and values["H2"].value is None
    parsed = tables.extract(patched, mappings)
    assert (
        next(entry for entry in parsed["entries"] if entry["date"] == today())["item_id"]
        == "excel-2"
    )
    repeated = upload(client, headers, patched)
    assert (
        client.post("/api/imports/confirm", json=approval(repeated), headers=headers).status_code
        == 200
    )
    assert client.get(f"/api/report/{today()}", headers=headers).json()["lines"] == report["lines"]


def test_ai_proposal_requires_confirmation_and_stale_plan_is_rejected(client, monkeypatch):
    ident, headers = imported_project(client, workbook())
    client.post(
        "/api/reports",
        json={"date": today(), "revision": 0, "lines": [{"item_id": "excel-2", "quantity": 5}]},
        headers=headers,
    )
    changed = workbook([("Прокладка кабеля 3х2,5", "м", 2)])
    preview = upload(client, headers, changed)
    workspaces.set_shared({"llm_api_key": "test-api-key"})

    async def complete(system, text, settings):
        payload = json.loads(text)
        assert payload["reports"] and payload["recent_changes"] and payload["entries"]
        assert "llm_api_key" not in text
        return {
            "matches": [
                {
                    "old_id": "excel-2",
                    "new_id": "excel-2",
                    "reason": "Тот же кабель, уточнено название",
                }
            ]
        }

    monkeypatch.setattr(matcher, "complete", complete)
    body = approval(preview)
    proposed = client.post("/api/imports/resolve", json=body, headers=headers)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["rows"][0]["method"] == "ai"
    body["position_matches"] = {"excel-2": "excel-2"}
    body["reconciliation_acknowledged"] = False
    assert client.post("/api/imports/confirm", json=body, headers=headers).status_code == 409
    client.post(
        "/api/reports",
        json={"date": today(), "revision": 1, "lines": [{"item_id": "excel-2", "quantity": 6}]},
        headers=headers,
    )
    body["reconciliation_acknowledged"] = True
    assert client.post("/api/imports/confirm", json=body, headers=headers).status_code == 409
    assert client.get(f"/api/report/{today()}", headers=headers).json()["lines"][0]["quantity"] == 6


def test_day_restore_cannot_modify_another_masters_reports(client):
    grant(client, "1001")
    ident = create(client, "1001")
    headers = {"X-Project-Id": ident, "X-Preview-User": "1001"}
    client.post(
        "/api/reports",
        json={"date": today(), "revision": 0, "lines": [{"item_id": "excel-17", "quantity": 5}]},
        headers=headers,
    )
    response = client.post(
        f"/api/report/{today()}/restore", json={"revision": 1}, headers={"X-Project-Id": ident}
    )
    assert response.status_code == 403


def test_explicit_crew_is_metadata_and_not_a_work_position():
    catalogue = [{"id": "cable", "name": "Монтаж кабеля 3х2,5", "unit": "м"}]
    result = matcher.local_parse(
        "Сегодня работал бригадой 5 человек, кабель 3х2,5 — 15 м", catalogue
    )
    assert result["crew_count"] == 5 and len(result["lines"]) == 1
    assert result["lines"][0]["item_id"] == "cable" and result["lines"][0]["quantity"] == 15
    assert matcher.local_parse("работали пять человек", catalogue)["lines"] == []
    ambiguous = matcher.local_parse("бригада 5 человек, потом 6 человек", catalogue)
    assert ambiguous["crew_count"] is None and ambiguous["crew_ambiguous"]


def test_conflict_can_accept_table_values_without_losing_audit(client):
    ident, headers = imported_project(client, workbook())
    client.post(
        "/api/reports",
        json={"date": today(), "revision": 0, "lines": [{"item_id": "excel-2", "quantity": 15}]},
        headers=headers,
    )
    changed = workbook()
    book = openpyxl.load_workbook(io.BytesIO(changed))
    book["Монтаж"]["H2"] = 10
    output = io.BytesIO()
    book.save(output)
    preview = upload(client, headers, output.getvalue())
    conflict = preview["reconciliation"]["report_conflicts"][0]
    assert conflict["lines"][0]["local"] == 15 and conflict["lines"][0]["remote"] == 10
    body = approval(preview)
    body["day_resolutions"] = {today(): "table"}
    response = client.post("/api/imports/confirm", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert (
        client.get(f"/api/report/{today()}", headers=headers).json()["lines"][0]["quantity"] == 10
    )
    event = client.get("/api/changes", headers={**headers, "X-View-Mode": "master"}).json()[0][
        "payload"
    ]
    assert event["reports_before"][today()]["lines"][0]["quantity"] == 15
