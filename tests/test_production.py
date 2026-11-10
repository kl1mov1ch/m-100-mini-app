import pytest
from fastapi.testclient import TestClient

from backend import service
from backend.runtime import configure_runtime


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
