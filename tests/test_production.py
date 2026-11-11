import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from backend import service
from backend.runtime import configure_runtime


def telegram_headers(ident, mode="admin"):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": ident})}
    key = hmac.new(b"WebAppData", b"123:test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(
        key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values), "X-View-Mode": mode}


def test_production_requires_bot_and_admin_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_FILE", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        configure_runtime()


def test_production_starts_without_demo_data_and_rejects_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "production.sqlite3"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "12345")
    monkeypatch.delenv("TELEGRAM_ROLE_SWITCH_ID", raising=False)
    monkeypatch.setenv("APP_ALLOWED_ORIGINS", "https://app.example.com")
    with TestClient(service.app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert (
            client.get("/api/session", headers={"X-Preview-User": "local-admin"}).status_code == 401
        )
        from backend import store, workspaces

        with store.connect() as database:
            assert database.execute("SELECT count(*) FROM positions").fetchone()[0] == 0
        with workspaces.registry() as database:
            assert database.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
            assert database.execute("SELECT telegram_id FROM users").fetchone()[0] == "12345"
        session = client.get("/api/session", headers=telegram_headers(12345, "master")).json()
        assert session["view_mode"] == "admin"
        assert session["can_switch_role"] is False


def test_only_reserved_admin_can_switch_roles_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "production.sqlite3"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "12345,12346")
    monkeypatch.setenv("TELEGRAM_ROLE_SWITCH_ID", "12345")
    monkeypatch.setenv("APP_ALLOWED_ORIGINS", "https://app.example.com")
    with TestClient(service.app) as client:
        assert (
            client.post(
                "/api/admin/users",
                headers=telegram_headers(12345),
                json={"telegram_id": "12347", "name": "Мастер", "role": "master"},
            ).status_code
            == 200
        )
        other_project = client.post(
            "/api/projects",
            headers=telegram_headers(12347),
            json={"name": "Другой объект"},
        ).json()["id"]
        admin_view = client.get("/api/session", headers=telegram_headers(12345)).json()
        assert other_project in {project["id"] for project in admin_view["projects"]}
        master_headers = telegram_headers(12345, "master")
        master_view = client.get("/api/session", headers=master_headers).json()
        assert master_view["can_switch_role"] and master_view["view_mode"] == "master"
        assert other_project not in {project["id"] for project in master_view["projects"]}
        assert client.get("/api/admin/users", headers=master_headers).status_code == 403
        assert client.get("/api/admin/users", headers=telegram_headers(12345)).status_code == 200
        for ident, requested, expected in ((12346, "master", "admin"), (12347, "admin", "master")):
            session = client.get("/api/session", headers=telegram_headers(ident, requested)).json()
            assert not session["can_switch_role"] and session["view_mode"] == expected
        assert client.get("/api/session", headers={"X-Preview-User": "12345"}).status_code == 401
