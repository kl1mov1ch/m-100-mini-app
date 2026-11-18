import asyncio
import base64
import io
import json
from datetime import date, timedelta
from zipfile import ZipFile

import httpx
import openpyxl
from openpyxl.styles import PatternFill
from test_reconciliation_restore import approval, upload, workbook
from test_workspaces import client, create, grant

from backend import bitrix, matcher, store, workbook_revision, workspaces
from backend.clock import today
from backend.table_editing import DailyColumnChange, apply_changes
from backend.workbook_journal import is_journal


def test_detach_replaces_table_issues_with_unsent_report_details(client):
    grant(client, "9001", "Мастер")
    ident = create(client, "9001", sample=False)
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        for key, value in {
            "source": "bitrix",
            "file_id": "123",
            "webhook": "configured",
            "bitrix_read_status": '{"status":"review"}',
            "bitrix_working_seen": "1",
            "bitrix_read_issues": '[{"kind":"layout","title":"Строка перемещена"}]',
        }.items():
            store.set_setting(db, key, value)
        db.execute(
            "INSERT INTO reports(date,revision,text,updated_at,sync_status,crew_count,author_id,sync_error) "
            "VALUES(?,1,'','','error',2,'9001','Нет доступа на запись')",
            (today(),),
        )
    endpoint = "/api/profile/table-notifications"
    before = next(item for item in client.get(endpoint).json() if item["project_id"] == ident)
    issue = next(issue for issue in before["issues"] if issue["kind"] == "sync")
    assert issue["author"] == "Мастер" and issue["reason"] == "Нет доступа на запись"

    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    assert client.post("/api/object/table/detach", headers=headers).is_success
    after = next(item for item in client.get(endpoint).json() if item["project_id"] == ident)
    assert after["can_check_table"] is False
    assert [issue["kind"] for issue in after["issues"]] == ["sync"]
    assert after["issues"][0]["reason"].startswith("Таблица отвязана")
    with store.connect(project["db_path"]) as db:
        assert store.setting(db, "bitrix_read_issues") == "[]"


def test_dismissed_table_notices_are_private_and_changed_issues_return(client):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    project = workspaces.project(workspaces.user("9001"), ident)
    headers = {"X-Preview-User": "9001"}
    with store.connect(project["db_path"]) as db:
        for key, value in {
            "source": "bitrix",
            "file_id": "123",
            "webhook": "configured",
            "bitrix_read_status": '{"status":"review"}',
            "bitrix_working_seen": "1",
            "bitrix_read_issues": '[{"kind":"layout","title":"Строка перемещена"}]',
        }.items():
            store.set_setting(db, key, value)
    path = "/api/profile/table-notifications"
    dismiss = path + f"/{ident}/dismiss"
    item = client.get(path, headers=headers).json()[0]["issues"][0]
    assert client.post(dismiss, json={"issue_id": item["id"]}, headers=headers).is_success
    assert client.get(path, headers=headers).json() == []
    assert client.get(path).json()[0]["issues"][0]["id"] == item["id"]
    assert client.post(dismiss, json={}).is_success
    assert client.get(path).json() == []
    with store.connect(project["db_path"]) as db:
        store.set_setting(
            db, "bitrix_read_issues", '[{"kind":"layout","title":"Удалена другая работа"}]'
        )
    assert (
        client.get(path, headers=headers).json()[0]["issues"][0]["title"] == "Удалена другая работа"
    )


def test_report_retries_with_bitrix_rates_and_preserves_remote_removed_work(client, monkeypatch):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, "webhook", "test-webhook")
        store.set_setting(db, "file_id", "123")
    current = workbook([("Монтаж кабеля 3х2,5", "м", 2), ("Монтаж светильника", "шт", 7)])
    writes = []

    async def download(*args):
        return current, {"NAME": "Смета.xlsx"}

    async def write(*args):
        nonlocal current
        current = base64.b64decode(args[2]["fileContent"][1])
        writes.append(current)
        return True

    def change_remote(address, value):
        book = openpyxl.load_workbook(io.BytesIO(current))
        next(sheet for sheet in book if is_journal(sheet))[address] = value
        stream = io.BytesIO()
        book.save(stream)
        return stream.getvalue()

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", write)
    preview = client.post("/api/imports/bitrix", headers=headers).json()
    confirmed = client.post("/api/imports/confirm", headers=headers, json=approval(preview))
    assert confirmed.is_success, confirmed.text
    positions = client.get("/api/bootstrap", headers=headers).json()["positions"]
    cable, light = [position["id"] for position in positions]
    current = change_remote("E5", 12.5)
    day = (date.fromisoformat(today()) - timedelta(days=2)).isoformat()
    first = client.post(
        "/api/reports",
        headers=headers,
        json={"date": day, "revision": 0, "lines": [{"item_id": cable, "quantity": 4}]},
    )
    assert first.is_success and first.json()["sync_status"] == "synced", first.text
    assert first.json()["payroll"]["amount"] == 50
    current = change_remote("B5", None)
    second = client.post(
        "/api/reports",
        headers=headers,
        json={"date": today(), "revision": 0, "lines": [{"item_id": light, "quantity": 3}]},
    )
    assert second.is_success and second.json()["sync_status"] == "synced", second.text
    assert second.json()["payroll"]["amount"] == 21 and len(writes) == 3
    historical = client.get(f"/api/report/{day}", headers=headers).json()
    assert historical["lines"][0]["quantity"] == 4 and historical["lines"][0]["deleted_at"]
    notice = client.get("/api/profile/table-notifications", headers=headers).json()[0]
    assert any(item["title"] == "Работа удалена из Битрикс24" for item in notice["issues"])


def test_admin_can_open_source_excel_without_exposing_webhook(client, monkeypatch):
    grant(client, "9001")
    grant(client, "9002")
    ident = create(client, "9001", sample=False)
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, "source", "bitrix")
        store.set_setting(db, "file_id", "123")
        store.set_setting(db, "webhook", "https://company.bitrix24.by/rest/1/private/")

    original = "https://company.bitrix24.by/company/personal/user/1/disk/file/estimate.xlsx"

    async def metadata(webhook, method, payload):
        assert method == "disk.file.get"
        assert payload == {"id": 123}
        return {"ID": "123", "NAME": "estimate.xlsx", "DETAIL_URL": original}

    monkeypatch.setattr(bitrix, "rest", metadata)
    endpoint = "/api/object/table/source"
    headers = {"X-Project-Id": ident}
    assert client.get(endpoint, headers=headers).json() == {"url": original}
    assert client.get(endpoint, headers={**headers, "X-Preview-User": "9002"}).status_code == 403


def test_original_sheet_review_rebuilds_working_sheets_after_confirmation(client, monkeypatch):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, "webhook", "test-webhook")
        store.set_setting(db, "file_id", "123")

    current = workbook()
    writes = []

    async def download(*args):
        return current, {"NAME": "Смета.xlsx"}

    async def write(*args):
        nonlocal current
        current = base64.b64decode(args[2]["fileContent"][1])
        writes.append(current)
        return True

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", write)
    initial = client.post("/api/imports/bitrix", headers=headers).json()
    confirmed = client.post("/api/imports/confirm", headers=headers, json=approval(initial))
    assert confirmed.is_success, confirmed.text
    assert len(writes) == 1
    assert client.post("/api/imports/bitrix?original=true", headers=headers).json() is None

    book = openpyxl.load_workbook(io.BytesIO(current))
    book["Монтаж"]["D2"] = "уточнить"
    second = book.create_sheet("Электрика")
    second.append(["Наименование", "Ед. изм.", "План", "Расценка"])
    second.append(["Розетка", "шт", 10, 9])
    stream = io.BytesIO()
    book.save(stream)
    current = stream.getvalue()
    review = client.post("/api/imports/bitrix?original=true", headers=headers).json()
    assert review["source_change"]["kind"] == "data"
    assert "Монтаж · D2" in review["source_change"]["locations"]
    changes = {"token": review["token"], "edits": [{"sheet": "Монтаж", "cell": "D2", "value": 5}]}
    edited = client.post("/api/imports/edit", headers=headers, json=changes)
    assert edited.is_success, edited.text
    assert len(writes) == 1
    confirmed = client.post("/api/imports/confirm", headers=headers, json=approval(edited.json()))
    assert confirmed.is_success, confirmed.text
    assert len(writes) == 2
    saved = openpyxl.load_workbook(io.BytesIO(current), data_only=True)
    assert saved["Монтаж"]["D2"].value == "уточнить"
    assert sum(is_journal(sheet) for sheet in saved) == 2
    assert sorted(item["rate"] for item in bitrix.read_workbook(current)["positions"]) == [5, 9]
    assert client.post("/api/imports/bitrix?original=true", headers=headers).json() is None


def test_live_overrun_preserves_confirmed_report_and_position_history(client, monkeypatch):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    content = workbook([("Монтаж блока", "шт", 2), ("Материал блока", "шт", 4)])
    preview = upload(client, headers, content)
    assert (
        client.post("/api/imports/confirm", json=approval(preview), headers=headers).status_code
        == 200
    )
    line = {"item_id": "excel-2", "quantity": 2}
    assert (
        client.post(
            "/api/reports", json={"date": today(), "revision": 0, "lines": [line]}, headers=headers
        ).status_code
        == 200
    )

    remote = openpyxl.load_workbook(io.BytesIO(content))
    sheet = remote.active
    sheet["C2"] = 4
    sheet["E2"] = 8
    sheet["F2"] = -4
    sheet["H2"] = 8
    sheet["I3"] = 9
    stream = io.BytesIO()
    remote.save(stream)
    selected = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(selected["db_path"]) as db:
        store.set_setting(db, "source", "bitrix")
        store.set_setting(db, "file_id", "123")
        store.set_setting(db, "webhook", "mock")

    attempts = []
    remote_content = stream.getvalue()

    async def read(*args):
        attempts.append(True)
        return remote_content, {"NAME": "Смета.xlsx"}

    monkeypatch.setattr(bitrix, "download_rest", read)
    assert client.post("/api/bitrix/refresh", headers=headers).json()["status"] == "current"
    assert all(
        issue["kind"] == "sync"
        for notice in client.get("/api/profile/table-notifications", headers=headers).json()
        for issue in notice["issues"]
    )
    from backend.workbook_journal import format_journal

    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    positions = bitrix.read_workbook(content, preview["sheets"])["positions"]
    positions[0]["planned"] = 4
    remote_content = format_journal(
        content,
        positions,
        [
            {"item_id": "excel-2", "date": today(), "quantity": 8},
            {"item_id": "excel-3", "date": yesterday, "quantity": 9},
        ],
        {},
        [],
    )
    with store.connect(selected["db_path"]) as db:
        store.set_setting(db, "bitrix_read_status", "null")
    first = client.post("/api/bitrix/refresh", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "review"
    assert client.post("/api/bitrix/refresh", headers=headers).json() == first.json()
    assert len(attempts) == 2
    data = client.get("/api/bootstrap", headers=headers).json()
    assert data["report"]["lines"] == [line]
    assert data["positions"][0]["bitrix"]["remaining"] == -4
    assert data["positions"][0]["bitrix"]["completed"] == 8
    assert not data["positions"][0]["hidden"]
    updated = client.get("/api/report/" + yesterday, headers=headers).json()
    assert {"item_id": "excel-3", "quantity": 9} in updated["lines"]

    path = "/api/object/positions/excel-2"
    history = client.get(path + "/history", headers=headers).json()
    assert {event["kind"] for event in history["events"]} >= {
        "report",
        "bitrix_values",
        "bitrix_day",
    }
    assert client.post(path, json={"action": "hide"}, headers=headers).status_code == 200
    updated = client.get("/api/bootstrap", headers=headers).json()
    assert updated["positions"][0]["hidden"]
    assert history["can_delete"] is True
    assert (
        client.post(path + "/consult", json={"question": "Почему −4?"}, headers=headers).status_code
        == 409
    )

    workspaces.set_shared({"llm_api_key": "test-key"})

    async def advice(system, text, settings):
        context = json.loads(text)
        assert context["position"]["bitrix"]["remaining"] == -4
        assert all("actor" not in event for event in context["history"]["events"])
        return {
            "answer": "Сравните объём в отчёте с Битрикс24.",
            "checks": ["Проверить запись за день"],
        }

    monkeypatch.setattr(matcher, "complete", advice)

    async def offline(*args):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bitrix, "download_rest", offline)
    with store.connect(selected["db_path"]) as db:
        read_status = first.json()
        read_status["checked_at"] = "2020-01-01T00:00:00+03:00"
        store.set_setting(db, "bitrix_read_status", json.dumps(read_status))
    read_status = client.post("/api/bitrix/refresh", headers=headers).json()
    assert read_status["status"] == "unavailable"
    data = client.get("/api/bootstrap", headers=headers).json()
    assert data["positions"][0]["bitrix"]["remaining"] == -4
    assert data["report"]["lines"] == [line]
    response = client.post(path + "/consult", json={"question": "Почему −4?"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["checks"]


def test_bitrix_reads_can_fall_back_to_server_proxy(monkeypatch):
    monkeypatch.setenv("BITRIX_PROXY_URL", "socks5://127.0.0.1:40001")
    calls = []

    async def read(proxy):
        calls.append(proxy)
        if proxy is None:
            raise httpx.ConnectError("direct route unavailable")
        return "workbook"

    assert asyncio.run(bitrix.read_with_fallback(read)) == "workbook"
    assert calls == [None, "socks5://127.0.0.1:40001"]


def test_bitrix_review_suggests_verified_values_without_editing_reports(client, monkeypatch):
    grant(client, "9001")
    grant(client, "9002")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    content = workbook([("Монтаж блока", "шт", 2), ("Прокладка трубы", "м", 4)])
    preview = upload(client, headers, content)
    assert client.post("/api/imports/confirm", json=approval(preview), headers=headers).is_success
    line = {"item_id": "excel-2", "quantity": 2}
    assert client.post(
        "/api/reports", json={"date": today(), "revision": 0, "lines": [line]}, headers=headers
    ).is_success
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "source", "bitrix")
        store.set_setting(database, "file_id", "123")
        store.set_setting(database, "webhook", "test-webhook")
        store.set_setting(
            database,
            "bitrix_read_status",
            json.dumps({"status": "review", "checked_at": "2020-01-01T00:00:00+03:00"}),
        )

    from backend.workbook_journal import format_journal

    positions = bitrix.read_workbook(content, preview["sheets"])["positions"]
    positions[0]["planned"] = 92
    generated = format_journal(
        content, positions, [{"item_id": "excel-2", "date": today(), "quantity": 8}], {}, []
    )
    remote = openpyxl.load_workbook(io.BytesIO(generated))
    remote.active["J6"] = "проверить"
    stream = io.BytesIO()
    remote.save(stream)

    async def read(*args):
        return stream.getvalue(), {"NAME": "Смета.xlsx"}

    monkeypatch.setattr(bitrix, "download_rest", read)
    path = "/api/bitrix/consult"
    assert client.post(path, headers={**headers, "X-Preview-User": "9002"}).status_code == 403
    assert client.post(path, headers={"X-Project-Id": ident}).status_code == 403
    response = client.post(path, headers=headers)
    assert response.is_success, response.text
    issues = {item["kind"]: item for item in response.json()["issues"]}
    assert "cell" in issues, response.json()
    assert issues["cell"]["cell"] == "J6"
    assert issues["planned"]["remote"] == 92
    assert response.json()["conflicts"]["days"] == 1
    assert response.json()["conflicts"]["positions"] == 1

    workspaces.set_shared({"llm_api_key": "test-key"})

    async def suggest(system, text, settings):
        assert "test-webhook" not in text
        assert any(item.get("remote") == 92 for item in json.loads(text))
        return {"advice": "Сверьте дневной отчёт и пересчитайте остаток."}

    monkeypatch.setattr(matcher, "complete", suggest)
    assert client.post(path + "?explain=true", headers=headers).json()["advice"]

    async def offline(*args):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(matcher, "complete", offline)
    assert client.post(path + "?explain=true", headers=headers).json() == {"advice": None}
    assert client.get("/api/report/" + today(), headers=headers).json()["lines"] == [line]

    async def unsupported_workbook(*args):
        return b"not an Excel file", {"NAME": "Смета.xlsx"}

    monkeypatch.setattr(bitrix, "download_rest", unsupported_workbook)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "bitrix_read_status", "null")
    assert client.post("/api/bitrix/refresh", headers=headers).json()["status"] == "review"
    assert client.post(path, headers=headers).json()["issues"][0]["kind"] == "layout"
    assert client.get("/api/report/" + today(), headers=headers).json()["lines"] == [line]


def test_import_suggests_from_cells_and_recovers_failed_journal_write(client, monkeypatch):
    grant(client, "9001")
    project_id = create(client, "9001", sample=False)
    headers = {"X-Project-Id": project_id, "X-Preview-User": "9001"}
    project = workspaces.project(workspaces.user("9001"), project_id)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "webhook", "test-webhook")
        store.set_setting(database, "file_id", "123")
    remote = openpyxl.load_workbook(
        io.BytesIO(
            workbook(
                [
                    ("Прокладка кабеля", "м", 2),
                    ("Монтаж щита", "шт", 5),
                ]
            )
        )
    )
    remote.calculation = None
    remote.active["H2"] = "12 м"
    remote.active["I2"] = "уточнить"
    remote.active["B3"] = None
    stream = io.BytesIO()
    remote.save(stream)
    current = stream.getvalue()

    async def read(*args):
        return current, {"NAME": "Смета.xlsx"}

    async def write(*args):
        nonlocal current

        current = base64.b64decode(args[2]["fileContent"][1])
        return True

    async def fail(*args):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bitrix, "download_rest", read)
    monkeypatch.setattr(bitrix, "rest", fail)
    preview = client.post("/api/imports/bitrix", headers=headers).json()
    body = approval(preview)
    workspaces.set_shared({"llm_api_key": "test-key"})

    async def model(system, text, settings):
        positions = json.loads(text)["positions"]
        return {"units": {positions[0]["id"]: "шт"}}

    monkeypatch.setattr(matcher, "complete", model)
    suggestions = client.post("/api/imports/consult", headers=headers, json=body).json()
    assert not any(issue.get("cell") == "H2" for issue in preview["warnings"])
    for cell, expected in (("I2", []), ("B3", ["шт"])):
        key = next(issue["id"] for issue in preview["warnings"] if issue.get("cell") == cell)
        assert [option["value"] for option in suggestions[key]["options"]] == expected
    confirmed = client.post("/api/imports/confirm", headers=headers, json=body)
    assert confirmed.is_success, confirmed.text
    assert confirmed.json()["journal"]["status"] == "pending"
    config = client.get("/api/bootstrap", headers=headers).json()["config"]
    assert not config["pending_import"] and config["journal_status"] == "pending"
    monkeypatch.setattr(bitrix, "rest", write)
    assert client.post("/api/bitrix/journal", headers=headers).json()["status"] == "ready"
    saved = openpyxl.load_workbook(io.BytesIO(current))
    assert saved["Монтаж"]["H2"].value == "12 м"
    assert "Журнал работ" in saved.sheetnames
    assert bitrix.day_values(bitrix.read_workbook(current), today())["excel-2"] == 12


def test_resolve_conflict_in_either_direction_and_reject_changed_snapshot(client, monkeypatch):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    original = current = workbook()
    preview = upload(client, headers, current)
    assert client.post("/api/imports/confirm", json=approval(preview), headers=headers).is_success
    exported = client.get("/api/imports/workbook.xlsx", headers=headers)
    assert is_journal(openpyxl.load_workbook(io.BytesIO(exported.content)).active)
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, "source", "bitrix")
        store.set_setting(db, "file_id", "123")
        store.set_setting(db, "webhook", "test-webhook")

    writes = []

    async def read(*args):
        return current, {"NAME": "Смета.xlsx"}

    async def write(*args):
        nonlocal current
        current = base64.b64decode(args[2]["fileContent"][1])
        writes.append(current)
        return True

    def edit_remote(value, rate=None):
        nonlocal current
        workbook = openpyxl.load_workbook(io.BytesIO(current))
        journal = workbook.active
        column = next(cell.column for cell in journal[3] if str(cell.value)[:10] == today())
        journal.cell(5, column).value = value
        if rate is not None:
            journal["E5"] = rate
        stream = io.BytesIO()
        workbook.save(stream)
        current = stream.getvalue()

    def review():
        with store.connect(project["db_path"]) as db:
            store.set_setting(db, "bitrix_read_status", "null")
        assert client.post("/api/bitrix/refresh", headers=headers).json()["status"] == "review"
        return client.post("/api/bitrix/consult", headers=headers).json()["conflicts"]

    monkeypatch.setattr(bitrix, "download_rest", read)
    monkeypatch.setattr(bitrix, "rest", write)
    save = {
        "date": today(),
        "revision": 0,
        "crew_count": 4,
        "lines": [{"item_id": "excel-2", "quantity": 4}],
    }
    first = client.post("/api/reports", headers=headers, json=save).json()
    assert first["sync_status"] == "synced"
    edit_remote(None)
    conflict = review()
    assert conflict["deleted"] == 1
    inbox = "/api/profile/table-notifications"
    with store.connect(project["db_path"]) as db:
        issues = json.loads(store.setting(db, "bitrix_read_issues"))
        issues.append({"kind": "appearance", "title": "Изменена заливка ячеек"})
        store.set_setting(db, "bitrix_read_issues", json.dumps(issues))
    notices = client.get(inbox, headers=headers).json()
    assert len(notices) == 1 and notices[0]["project_id"] == ident
    assert any(issue["kind"] == "report" and issue["remote"] == 0 for issue in notices[0]["issues"])
    assert all(issue["kind"] != "appearance" for issue in notices[0]["issues"])
    admin_notice = next(
        notice for notice in client.get(inbox).json() if notice["project_id"] == ident
    )
    assert admin_notice["version"] is None
    refresh_notice = f"{inbox}/{ident}/refresh"
    assert client.post(refresh_notice, json={"version": conflict["version"]}).status_code == 403
    result = client.post(
        refresh_notice,
        headers=headers,
        json={"version": notices[0]["version"]},
    )
    assert result.is_success, result.text
    assert all(
        notice["project_id"] != ident for notice in client.get(inbox, headers=headers).json()
    )
    saved = client.get("/api/report/" + today(), headers=headers).json()
    assert saved["lines"] == [] and len(writes) == 1

    save["revision"] = saved["revision"]
    assert client.post("/api/reports", headers=headers, json=save).json()["sync_status"] == "synced"
    edit_remote(9, 3)
    conflict = review()
    assert conflict["days"] == 1 and conflict["fields"] == 1
    edit_remote(10, 3)
    stale = client.post(
        "/api/bitrix/reconcile",
        headers=headers,
        json={"direction": "table", "version": conflict["version"]},
    )
    assert stale.status_code == 409 and len(writes) == 2
    conflict = review()
    resolved = client.post(
        "/api/bitrix/reconcile",
        headers=headers,
        json={"direction": "table", "version": conflict["version"]},
    )
    assert resolved.is_success, resolved.text
    parsed = bitrix.read_workbook(current)
    assert bitrix.day_values(parsed, today()) == {"excel-2": 4}
    assert parsed["positions"][0]["rate"] == 2 and parsed["crew_by_day"][today()] == 4
    assert len(writes) == 3
    sheet = openpyxl.load_workbook(io.BytesIO(original), data_only=False).active
    copied = openpyxl.load_workbook(io.BytesIO(current), data_only=False)[sheet.title]
    assert list(sheet.values) == list(copied.values)


def test_daily_column_errors_are_grouped_and_fixed_in_one_action():
    from backend import tables

    book = openpyxl.load_workbook(
        io.BytesIO(workbook([(f"Работа {row}", "м", 2) for row in range(70)]))
    )
    sheet = book.active
    for row in range(2, 72):
        sheet.cell(row, 8, "удалено")
    stream = io.BytesIO()
    book.save(stream)
    content = stream.getvalue()
    mappings, _ = tables.discover(content)
    warnings = tables.extract(content, mappings)["warnings"]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["cell"] == "H2:H71" and len(warning["affected_rows"]) == 70
    for strategy, expected in (("zero", 0), ("remove", None), ("restore", 7)):
        column = DailyColumnChange(sheet=sheet.title, column="H", date=today(), strategy=strategy)
        restoration = {today(): {f"excel-{row}": 7 for row in range(2, 72)}}
        updated, changes = apply_changes(content, mappings, [], [], [column], restoration)
        result = openpyxl.load_workbook(io.BytesIO(updated)).active
        assert all(result.cell(row, 8).value == expected for row in range(2, 72))
        assert result["I2"].value == 7 and len(changes) >= 70
        assert bool(result.column_dimensions["H"].hidden) == (strategy == "remove")
        assert tables.extract(updated, mappings)["warnings"] == []


def test_bitrix_initial_correction_stays_in_draft_and_rechecks_original_at_confirmation(
    client, monkeypatch
):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    project = workspaces.project(workspaces.user("9001"), ident)
    original = current = workbook()
    writes = []
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, "webhook", "test-webhook")
        store.set_setting(db, "file_id", "123")

    async def download(*args):
        return current, {"NAME": "Смета.xlsx"}

    async def write(*args):
        nonlocal current
        current = base64.b64decode(args[2]["fileContent"][1])
        writes.append(current)
        return True

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", write)
    preview = client.post("/api/imports/bitrix", headers=headers).json()
    repacked = io.BytesIO()
    with ZipFile(io.BytesIO(original)) as source, ZipFile(repacked, "w") as target:
        for name in source.namelist():
            part = source.read(name)
            target.writestr(
                name,
                part.replace(b'topLeftCell="A1"', b'topLeftCell="A2"') + b"\n"
                if name == "xl/worksheets/sheet1.xml"
                else part,
            )
    current = repacked.getvalue()
    assert original != current and workbook_revision.changes(original, current) is None
    edit = {
        "token": preview["token"],
        "edits": [{"sheet": "Монтаж", "cell": "D2", "value": "12,5"}],
    }
    result = client.post("/api/imports/edit", json=edit, headers=headers)
    assert result.is_success, result.text
    assert not writes and result.json()["saved_to_source"] is False
    assert result.json()["positions"][0]["rate"] == 12.5
    second = {**edit, "edits": [{"sheet": "Монтаж", "cell": "C2", "value": "99"}]}
    staged = client.post("/api/imports/edit", json=second, headers=headers)
    assert staged.is_success and staged.json()["positions"][0]["rate"] == 12.5

    book = openpyxl.load_workbook(io.BytesIO(current))
    book.active["D2"].fill = PatternFill("solid", fgColor="FFFF00")
    stream = io.BytesIO()
    book.save(stream)
    current = stream.getvalue()
    rejected = client.post("/api/imports/confirm", json=approval(staged.json()), headers=headers)
    assert rejected.status_code == 409 and not writes
    latest = client.get("/api/imports/pending", headers=headers).json()
    assert latest["source_change"]["kind"] == "appearance"
    assert latest["token"] != edit["token"]
    edit["token"] = latest["token"]
    corrected = client.post("/api/imports/edit", json=edit, headers=headers)
    assert corrected.is_success
    assert client.post(
        "/api/imports/confirm", json=approval(corrected.json()), headers=headers
    ).is_success
    assert len(writes) == 1
    book = openpyxl.load_workbook(io.BytesIO(current))
    assert book["Монтаж"]["D2"].fill.fgColor.rgb.endswith("FFFF00")
    assert next(sheet for sheet in book if is_journal(sheet))["E5"].value == 12.5
