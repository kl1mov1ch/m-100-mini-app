import asyncio
import io
import json
from datetime import date, timedelta

import httpx
import openpyxl

from backend import bitrix, matcher, store, workspaces
from backend.clock import today
from test_reconciliation_restore import approval, upload, workbook
from test_workspaces import client, create, grant


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

    async def read(*args):
        attempts.append(True)
        return stream.getvalue(), {"NAME": "Смета.xlsx"}

    monkeypatch.setattr(bitrix, "download_rest", read)
    first = client.post("/api/bitrix/refresh", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "review"
    assert client.post("/api/bitrix/refresh", headers=headers).json() == first.json()
    assert len(attempts) == 1
    data = client.get("/api/bootstrap", headers=headers).json()
    assert data["report"]["lines"] == [line]
    assert data["positions"][0]["bitrix"]["remaining"] == -4
    assert data["positions"][0]["bitrix"]["completed"] == 8
    assert not data["positions"][0]["hidden"]
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
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
    assert history["can_delete"] is False
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

    remote = openpyxl.load_workbook(io.BytesIO(content))
    remote.active["E2"] = 8
    remote.active["F2"] = 9
    remote.active["H2"] = 8
    remote.active["H3"] = "проверить"
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
    assert issues["cell"]["cell"] == "H3"
    assert issues["remaining"]["cell"] == "F2"
    assert issues["remaining"]["remote"] == 9 and issues["remaining"]["suggested"] == 92
    assert issues["remaining"]["formula"] == "=C2-E2"
    assert issues["report"]["local"] == 2 and issues["report"]["remote"] == 8
    assert "suggested" not in issues["report"]

    workspaces.set_shared({"llm_api_key": "test-key"})

    async def suggest(system, text, settings):
        assert "test-webhook" not in text
        assert any(item.get("suggested") == 92 for item in json.loads(text))
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
        import base64

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
    for cell, expected in (("H2", [12]), ("I2", []), ("B3", ["шт"])):
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
