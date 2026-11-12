import os
import secrets
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_reconciliation_restore import approval, upload, workbook
from test_workspaces import create, grant

from backend import postgres, store, workspaces
from backend.clock import today
from backend.service import app
from scripts.data_archive import backup
from scripts.migrate_postgres import migrate


def test_sqlite_migration_and_report_lifecycle(tmp_path, monkeypatch):
    owner = os.getenv("APP_TEST_PG_OWNER_URL")
    if not owner:
        pytest.skip("Set APP_TEST_PG_OWNER_URL to an isolated PostgreSQL test server")

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_STORAGE", "sqlite")
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "source.sqlite3"))
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "9999")
    day = today()
    with TestClient(app) as client:
        grant(client, "7001")
        grant(client, "7002")
        first = create(client, "7001", sample=False)
        second = create(client, "7002", sample=False)
        headers = {"X-Project-Id": first, "X-Preview-User": "7001"}
        for ident, master in ((first, "7001"), (second, "7002")):
            project_headers = {"X-Project-Id": ident, "X-Preview-User": master}
            preview = upload(client, project_headers, workbook())
            assert (
                client.post(
                    "/api/imports/confirm", json=approval(preview), headers=project_headers
                ).status_code
                == 200
            )
        response = client.post(
            "/api/reports",
            json={"date": day, "revision": 0, "lines": [{"item_id": "excel-2", "quantity": 10}]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["payroll"]["amount"] == 20
    archive = tmp_path / "source.zip"
    backup(archive)

    identifier = "qa_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    with psycopg.connect(owner, autocommit=True) as cluster:
        cluster.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(identifier), sql.Literal(password)
            )
        )
        try:
            cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(identifier)))
            try:
                with psycopg.connect(make_conninfo(owner, dbname=identifier)) as database:
                    copied = migrate(database, archive, identifier, tmp_path)
                    assert copied["projects"][first]["reports"] == 1
                    assert copied["projects"][first]["day_snapshots"] == 1
                monkeypatch.setenv("APP_STORAGE", "postgres")
                monkeypatch.setenv(
                    "DATABASE_URL",
                    make_conninfo(owner, dbname=identifier, user=identifier, password=password),
                )
                with TestClient(app) as client:
                    report = client.get(f"/api/report/{day}", headers=headers).json()
                    assert report["lines"][0]["quantity"] == 10
                    assert report["payroll"]["amount"] == 20
                    denied = client.get(
                        f"/api/report/{day}", headers={**headers, "X-Project-Id": second}
                    )
                    assert denied.status_code == 403
                    with store.connect(f"project:{first}") as database:
                        assert not database.execute(
                            "SELECT id FROM positions WHERE project_id=?", (second,)
                        ).fetchall()
                    preview = upload(client, headers, workbook())
                    response = client.post(
                        "/api/imports/confirm", json=approval(preview), headers=headers
                    )
                    assert response.status_code == 200, response.text
                    report = client.get(f"/api/report/{day}", headers=headers).json()
                    edited = client.post(
                        "/api/reports",
                        json={
                            "date": day,
                            "revision": report["revision"],
                            "lines": [{"item_id": "excel-2", "quantity": 4.25}],
                        },
                        headers=headers,
                    )
                    assert edited.status_code == 200, edited.text
                    assert edited.json()["payroll"]["amount"] == 8.5
                    restored = client.post(
                        f"/api/report/{day}/restore",
                        json={"revision": edited.json()["revision"]},
                        headers=headers,
                    )
                    assert restored.status_code == 200, restored.text
                    assert restored.json()["payroll"]["amount"] == 0
                    webhook = client.post(
                        "/api/profile/disk-webhooks",
                        headers=headers,
                        json={
                            "name": "Портал",
                            "url": "https://example.bitrix24.by/rest/1/ormCheck/",
                        },
                    )
                    assert webhook.status_code == 200, webhook.text
                    webhook_id = webhook.json()["id"]
                    edited_hook = client.post(
                        f"/api/profile/disk-webhooks/{webhook_id}/update",
                        headers=headers,
                        json={"name": "Обновлён"},
                    )
                    assert edited_hook.status_code == 200, edited_hook.text
                    assert (
                        client.post(
                            f"/api/profile/disk-webhooks/{webhook_id}/delete",
                            headers=headers,
                            json={},
                        ).status_code
                        == 200
                    )
                    exported = client.get(
                        "/api/analytics/export.xlsx", params={"project_id": first}, headers=headers
                    )
                    assert exported.status_code == 200, (
                        exported.text[:100] if exported.status_code != 200 else ""
                    )
                    with pytest.raises(RuntimeError), store.connect(f"project:{first}") as database:
                        store.set_setting(database, "transaction_rollback_test", "not committed")
                        raise RuntimeError("rollback")
                    with store.connect(f"project:{first}") as database:
                        assert store.setting(database, "transaction_rollback_test") == ""
                    assert workspaces.user("7001")["role"] == "master"
                    assert create(client, "7001", sample=True)
                    assert (
                        client.post(
                            "/api/object/delete", json={"name": "Объект"}, headers=headers
                        ).status_code
                        == 200
                    )
                    assert not workspaces.exists(first)
                    assert workspaces.exists(second)
            finally:
                postgres.close_pool()
                cluster.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(identifier)))
        finally:
            cluster.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(identifier)))
