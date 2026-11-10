import io
import json
import hashlib
import hmac
import time
from urllib.parse import urlencode
import openpyxl
import pytest
from fastapi.testclient import TestClient
from backend import service, store, workspaces, bitrix, tables


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with TestClient(service.app) as c:
        yield c


def grant(client, ident, name="Мастер"):
    assert (
        client.post("/api/admin/users", json={"telegram_id": ident, "name": name}).status_code
        == 200
    )


def create(client, ident="local-admin", sample=True, name="Объект"):
    r = client.post(
        "/api/projects",
        json={"name": name, "sample": sample},
        headers={"X-Preview-User": ident},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_master_isolation_including_uploads(client):
    grant(client, "1001", "Мастер 1")
    grant(client, "1002", "Мастер 2")
    first = create(client, "1001")
    second = create(client, "1002")
    h = {"X-Preview-User": "1001", "X-Project-Id": second}
    for path in (
        "/api/bootstrap",
        "/api/changes",
        "/api/report/" + service.today(),
        "/api/export.csv",
    ):
        assert client.get(path, headers=h).status_code == 403
    assert client.post("/api/search", json={"text": "медь"}, headers=h).status_code == 403
    assert client.get("/api/admin/users", headers={"X-Preview-User": "1001"}).status_code == 403
    assert [
        p["id"]
        for p in client.get("/api/session", headers={"X-Preview-User": "1001"}).json()["projects"]
    ] == [first]
    assert len(client.get("/api/session").json()["projects"]) == 3


def test_revocation_takes_effect_and_no_self_assignment(client):
    grant(client, "1001")
    create(client, "1001")
    assert (
        client.post(
            "/api/projects",
            json={"name": "Чужой", "owner_id": "local-admin"},
            headers={"X-Preview-User": "1001"},
        ).status_code
        == 403
    )
    client.post(
        "/api/admin/users",
        json={"telegram_id": "1001", "name": "Мастер", "enabled": False},
    )
    assert client.get("/api/session", headers={"X-Preview-User": "1001"}).status_code == 403


def test_exact_payroll_no_op_and_changes(client):
    ident = create(client)
    h = {"X-Project-Id": ident}
    body = {
        "date": service.today(),
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 10.01}],
        "crew_count": 3,
    }
    r = client.post("/api/reports", json=body, headers=h)
    assert r.status_code == 200, r.text
    result = r.json()
    p = result["payroll"]
    assert p["amount"] == 100.1 and p["per_person"] == 33.36 and p["extra_people"] == 2
    assert round(p["per_person"] * 3 + p["extra_people"] * 0.01, 2) == p["amount"]
    body["revision"] = 1
    repeated = client.post("/api/reports", json=body, headers=h).json()
    assert repeated["changed"] is False and repeated["revision"] == 1
    body["crew_count"] = 5
    updated = client.post("/api/reports", json=body, headers=h).json()
    assert updated["revision"] == 2 and updated["payroll"]["per_person"] == 20.02
    events = client.get("/api/changes", headers=h).json()
    assert len(events) == 2 and events[0]["payload"]["changes"]["crew_after"] == 5


def test_auto_sync_after_confirmation_only_when_changed(client, monkeypatch):
    ident = create(client)
    h = {"X-Project-Id": ident}
    p = workspaces.project(workspaces.user("local-admin"), ident)
    calls = []
    with store.connect(p["db_path"]) as db:
        store.set_setting(db, "source", "bitrix")
        store.set_setting(db, "webhook", "configured-in-test")

    async def upload(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(bitrix, "upload_day", upload)
    body = {
        "date": service.today(),
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 15}],
        "crew_count": 5,
    }
    r = client.post("/api/reports", json=body, headers=h).json()
    assert r["sync_status"] == "synced" and len(calls) == 1 and calls[0][5]["crew_count"] == 5
    body["revision"] = 1
    client.post("/api/reports", json=body, headers=h)
    assert len(calls) == 1


def make_workbook(ambiguous=False, multi=False):
    w = openpyxl.Workbook()
    s = w.active
    s.title = "Монтаж"
    s.append(["Проект: объект 1"])
    s.append([])
    s.append(["Работа", "Цена", "Ед. изм.", "Количество"])
    s.append(["Монтаж кабеля 3х2,5", 2.35, "м", 100])
    if ambiguous:
        s.append(["Монтаж трубы", "неизвестно", "м", 40])
    if multi:
        t = w.create_sheet("Вентиляция")
        t.append(["Наименование", "Единица", "Расценка", "План"])
        t.append(["Воздуховод", "м", 4.5, 70])
    output = io.BytesIO()
    w.save(output)
    return output.getvalue()


def test_flexible_upload_mapping_full_sheets_and_yellow_ack(client):
    ident = create(client, sample=False)
    h = {"X-Project-Id": ident}
    r = client.post(
        "/api/imports/upload",
        files={
            "file": (
                "custom.xlsx",
                make_workbook(True, True),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert len(preview["sheets"]) == 2 and len(preview["positions"]) == 3 and preview["warnings"]
    assert (
        preview["sheets"][0]["mapping"]["rate"] == 2
        and preview["sheets"][0]["mapping"]["name"] == 1
    )
    body = {"token": preview["token"], "sheets": preview["sheets"], "acknowledged": []}
    assert client.post("/api/imports/confirm", json=body, headers=h).status_code == 422
    body["acknowledged"] = [w["id"] for w in preview["warnings"]]
    assert client.post("/api/imports/confirm", json=body, headers=h).status_code == 200
    data = client.get("/api/bootstrap", headers=h).json()
    assert len(data["positions"]) == 3 and data["positions"][0]["source_sheet"]
    other = create(client, sample=False)
    assert (
        client.post("/api/imports/confirm", json=body, headers={"X-Project-Id": other}).status_code
        == 403
    )


def test_csv_and_generic_excel_write_preserve_other_values(client):
    ident = create(client, sample=False)
    h = {"X-Project-Id": ident}
    raw = "Название работы;Расценка;Ед. изм.;План\nМонтаж кабеля;2,35;м;100\n".encode("utf-8")
    r = client.post(
        "/api/imports/upload", files={"file": ("table.csv", raw, "text/csv")}, headers=h
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["positions"][0]["rate"] == 2.35
    content = make_workbook(multi=True)
    descs, _ = tables.discover(content)
    data = tables.extract(content, descs)
    q = [{"item_id": data["positions"][0]["id"], "quantity": 15}]
    patched = tables.patch(content, service.today(), q, data["positions"], descs)
    s = openpyxl.load_workbook(io.BytesIO(patched))["Монтаж"]
    assert s["B4"].value == 2.35 and s["D4"].value == 100 and s["E4"].value == 15
    assert openpyxl.load_workbook(io.BytesIO(patched))["Вентиляция"]["C2"].value == 4.5


def test_production_ignores_preview_header(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/api/session", headers={"X-Preview-User": "local-admin"}).status_code == 401


def test_browser_origin_and_master_access_are_checked_separately(client):
    response = client.post(
        "/api/admin/users",
        json={"telegram_id": "2001", "name": "Мастер"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 200
    denied = client.post(
        "/api/admin/users",
        json={"telegram_id": "2002", "name": "Другой"},
        headers={"Origin": "http://127.0.0.1:5173", "X-Preview-User": "2001"},
    )
    assert denied.status_code == 403
    blocked = client.post(
        "/api/admin/users",
        json={"telegram_id": "2003", "name": "Другой"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert blocked.status_code == 403


def test_admin_can_choose_report_date(client):
    bootstrap = client.get("/api/bootstrap").json()
    historical_day = bootstrap["history"][-1]
    response = client.get("/api/session?date=" + historical_day["date"])
    assert response.status_code == 200
    summary = response.json()
    assert summary["selected_date"] == historical_day["date"]
    assert summary["projects"][0]["today_amount"] == historical_day["amount"]
    assert historical_day["date"] in summary["projects"][0]["work_dates"]


def test_import_problem_identifies_cell_and_fix(client):
    object_id = create(client, sample=False)
    response = client.post(
        "/api/imports/upload",
        files={
            "file": (
                "custom.xlsx",
                make_workbook(ambiguous=True),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers={"X-Project-Id": object_id},
    )
    assert response.status_code == 200
    issue = next(warning for warning in response.json()["warnings"] if warning.get("cell") == "B5")
    assert issue["sheet"] == "Монтаж" and issue["row"] == 5 and issue["column"] == "B"
    assert issue["value"] == "неизвестно" and issue["position_name"] == "Монтаж трубы"
    assert "B5" in issue["fix"] and issue["confirmation_label"] == "Принять нулевую расценку"
