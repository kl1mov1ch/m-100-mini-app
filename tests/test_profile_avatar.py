import time
from urllib.parse import parse_qs

import httpx

from backend import profile, workspaces
from test_workspaces import client, grant


def mock_telegram(monkeypatch, answer):
    original_client = httpx.AsyncClient
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setattr(
        profile.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(answer)),
    )


def test_avatar_uses_current_telegram_photo_and_caches_private_bytes(client, monkeypatch):
    grant(client, "1001")
    requests = []

    def answer(request):
        requests.append(request)
        if request.url.path.endswith("getUserProfilePhotos"):
            assert parse_qs(request.content.decode())["user_id"] == ["1001"]
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"photos": [[{"file_id": "small"}, {"file_id": "large"}]]},
                },
            )
        if request.url.path.endswith("getFile"):
            assert parse_qs(request.content.decode())["file_id"] == ["large"]
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "photos/current.jpg"}}
            )
        return httpx.Response(200, content=b"current-photo", headers={"Content-Type": "image/jpeg"})

    mock_telegram(monkeypatch, answer)
    headers = {"X-Preview-User": "1001"}
    response = client.get("/api/profile/avatar", headers=headers)
    assert response.status_code == 200
    assert response.content == b"current-photo"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/profile/avatar", headers=headers).content == b"current-photo"
    assert len(requests) == 3
    assert client.get("/api/profile/avatar?refresh=true", headers=headers).status_code == 200
    assert len(requests) == 6


def test_master_cannot_load_other_users_photo(client, monkeypatch):
    grant(client, "1001")
    grant(client, "1002")

    def unexpected_request(request):
        raise AssertionError("Чужое фото не должно запрашиваться в Telegram")

    mock_telegram(monkeypatch, unexpected_request)
    assert (
        client.get(
            "/api/profile/avatar?user_id=1002", headers={"X-Preview-User": "1001"}
        ).status_code
        == 403
    )


def test_avatar_retains_cached_photo_when_telegram_is_unavailable(client, monkeypatch):
    grant(client, "1001")
    with workspaces.registry() as database:
        database.execute(
            "INSERT INTO profile_avatars VALUES(?,?,?,?)",
            ("1001", b"last-photo", "image/jpeg", int(time.time()) - 600),
        )

    def unavailable(request):
        return httpx.Response(503, json={"ok": False})

    mock_telegram(monkeypatch, unavailable)
    response = client.get("/api/profile/avatar", headers={"X-Preview-User": "1001"})
    assert response.status_code == 200 and response.content == b"last-photo"
    with workspaces.registry() as database:
        assert (
            database.execute(
                "SELECT content FROM profile_avatars WHERE telegram_id='1001'"
            ).fetchone()[0]
            == b"last-photo"
        )


def test_avatar_handles_absent_photo_without_repeated_requests(client, monkeypatch):
    grant(client, "1001")
    requests = []

    def no_photo(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"photos": []}})

    mock_telegram(monkeypatch, no_photo)
    headers = {"X-Preview-User": "1001"}
    assert client.get("/api/profile/avatar", headers=headers).status_code == 404
    assert client.get("/api/profile/avatar", headers=headers).status_code == 404
    assert len(requests) == 1


def test_avatar_proxies_verified_telegram_photo_when_bot_cannot_see_it(client, monkeypatch):
    grant(client, "1001")
    with workspaces.registry() as database:
        database.execute(
            "UPDATE users SET avatar_url=? WHERE telegram_id=?",
            ("https://t.me/i/userpic/320/current.jpg", "1001"),
        )

    def answer(request):
        assert request.url.host == "t.me"
        return httpx.Response(200, content=b"current-photo", headers={"Content-Type": "image/jpeg"})

    mock_telegram(monkeypatch, answer)
    response = client.get("/api/profile/avatar", headers={"X-Preview-User": "1001"})
    assert response.status_code == 200 and response.content == b"current-photo"
    assert not profile.telegram_photo_url("https://t.me.evil.test/i/userpic/320/photo.jpg")
    assert not profile.telegram_photo_url("https://127.0.0.1/i/userpic/320/photo.jpg")
