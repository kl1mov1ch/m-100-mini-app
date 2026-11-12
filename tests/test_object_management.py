from fastapi.testclient import TestClient

from backend import bitrix, service, store, workspaces
from backend.imports import directory
from test_reconciliation_restore import approval, upload, workbook
from test_workspaces import client, create, grant


def test_pending_table_review_belongs_to_master(client):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    admin = {"X-Project-Id": ident}
    master = {**admin, "X-Preview-User": "9001"}
    preview = upload(client, master, workbook())
    assert client.get("/api/imports/pending", headers=master).json()["token"] == preview["token"]
    assert client.get("/api/imports/pending", headers=admin).json() is None
    assert not client.get("/api/bootstrap", headers=admin).json()["config"]["pending_import"]
    assert client.get("/api/bootstrap", headers=master).json()["config"]["pending_import"]
    projects = client.get("/api/session", headers=admin).json()["projects"]
    assert not next(item for item in projects if item["id"] == ident)["table"]["pending_review"]


def test_detach_keeps_reports_and_disables_retry(client, monkeypatch):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    preview = upload(client, headers, workbook())
    assert (
        client.post("/api/imports/confirm", json=approval(preview), headers=headers).status_code
        == 200
    )
    day = service.today()
    line = {"item_id": "excel-2", "quantity": 2}
    saved = client.post(
        "/api/reports", json={"date": day, "revision": 0, "lines": [line]}, headers=headers
    )
    assert saved.status_code == 200
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        for key, value in {
            "source": "bitrix",
            "file_id": "123",
            "webhook": "https://example.test/rest/1/secret/",
            "pending_import_token": preview["token"],
        }.items():
            store.set_setting(db, key, value)

    async def forbidden(*args, **kwargs):
        raise AssertionError("A detached object must never upload")

    monkeypatch.setattr(bitrix, "upload_day", forbidden)
    assert (
        client.post("/api/object/table/detach", headers={"X-Project-Id": ident}).status_code == 403
    )
    assert client.post("/api/object/table/detach", headers=headers).status_code == 200
    data = client.get("/api/bootstrap", headers=headers).json()
    assert data["config"]["source"] == "detached"
    assert not data["config"]["has_webhook"]
    assert not data["config"]["pending_import"]
    assert data["report"]["lines"] == [line]
    assert data["positions"]
    assert not client.post(f"/api/bitrix/sync/{day}", headers=headers).json()["ok"]
    assert client.post("/api/imports/bitrix", headers=headers).status_code == 422


def test_hidden_and_deleted_positions_do_not_break_history(client):
    grant(client, "9001")
    ident = create(client, "9001", sample=False)
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    preview = upload(client, headers, workbook())
    assert (
        client.post("/api/imports/confirm", json=approval(preview), headers=headers).status_code
        == 200
    )
    project = workspaces.project(workspaces.user("9001"), ident)
    with store.connect(project["db_path"]) as db:
        store.insert_position(
            db,
            dict(id="unused", name="Unused", section="", unit="м", rate=1, planned=4, source_row=9),
        )
    day = service.today()
    line = {"item_id": "excel-2", "quantity": 2}
    assert (
        client.post(
            "/api/reports", json={"date": day, "revision": 0, "lines": [line]}, headers=headers
        ).status_code
        == 200
    )
    path = "/api/object/positions/"
    assert (
        client.post(path + "excel-2", json={"action": "delete"}, headers=headers).status_code == 409
    )
    assert (
        client.post(path + "excel-2", json={"action": "hide"}, headers=headers).status_code == 409
    )
    with store.connect(project["db_path"]) as db:
        db.execute("UPDATE positions SET planned=1 WHERE id='excel-2'")
    assert (
        client.post(path + "excel-2", json={"action": "hide"}, headers=headers).status_code == 200
    )
    assert (
        client.post(path + "unused", json={"action": "delete"}, headers=headers).status_code == 200
    )
    data = client.get("/api/bootstrap", headers=headers).json()
    assert [(p["id"], p["hidden"]) for p in data["positions"]] == [("excel-2", True)]
    assert data["report"]["payroll"]["amount"] == 4
    with store.connect(project["db_path"]) as db:
        assert store.selectable_positions(db) == []
    assert (
        client.post(
            "/api/reports", json={"date": day, "revision": 1, "lines": []}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(path + "excel-2", json={"action": "delete"}, headers=headers).status_code == 409
    )
    assert (
        client.post(path + "excel-2", json={"action": "show"}, headers=headers).status_code == 200
    )


def test_delete_object_requires_owner_and_exact_name(client):
    grant(client, "9001")
    ident = create(client, "9001", sample=False, name="Тестовый объект")
    headers = {"X-Project-Id": ident, "X-Preview-User": "9001"}
    preview = upload(client, headers, workbook())
    original = directory() / (preview["token"] + ".xlsx")
    assert original.is_file()
    assert (
        client.post(
            "/api/object/delete", json={"name": "Тестовый объект"}, headers={"X-Project-Id": ident}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/object/delete", json={"name": "Другой"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/api/object/delete", json={"name": "Тестовый объект"}, headers=headers
        ).status_code
        == 200
    )
    assert not original.exists()
    assert client.get("/api/session", headers=headers).json()["projects"] == []
    assert client.get("/api/bootstrap", headers=headers).status_code == 403


def test_deleted_default_is_not_recreated(client):
    headers = {"X-Project-Id": "default", "X-View-Mode": "master"}
    assert (
        client.post("/api/object/delete", json={"name": "Детский сад"}, headers=headers).status_code
        == 200
    )
    with TestClient(service.app) as restarted:
        assert restarted.get("/api/session", headers=headers).json()["projects"] == []
