import io
import uuid
from urllib.parse import parse_qs

import httpx
import openpyxl

from backend import notifications, report_downloads, workspaces
from backend.clock import today
from test_workspaces import client, create, grant


def test_reminders_only_target_missing_reports_and_deduplicate(client, monkeypatch):
    for user in ("1001", "1002", "1003"):
        grant(client, user)
    submitted = create(client, "1001")
    missing = create(client, "1002")
    create(client, "1003", sample=False)
    client.post(
        "/api/reports",
        json={"date": today(), "revision": 0, "lines": [{"item_id": "excel-17", "quantity": 15}]},
        headers={"X-Preview-User": "1001", "X-Project-Id": submitted},
    )
    recipients = client.get("/api/admin/reminders").json()["recipients"]
    assert [item["telegram_id"] for item in recipients] == ["1002"]
    assert client.get("/api/admin/reminders", headers={"X-Preview-User": "1002"}).status_code == 403
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "9001")
    sent = []

    def answer(request):
        sent.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        notifications.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(answer)),
    )
    body = {"request_id": str(uuid.uuid4())}
    assert client.post("/api/admin/reminders/send", json=body).json()["sent"] == 1
    assert client.post("/api/admin/reminders/send", json=body).json()["skipped"] == 1
    assert len(sent) == 1 and sent[0]["chat_id"] == ["1002"]
    assert (
        client.post("/api/admin/reminders/test", json={"request_id": str(uuid.uuid4())}).json()[
            "sent"
        ]
        == 1
    )
    assert sent[-1]["chat_id"] == ["9001"]
    assert notifications.missing_reports(today())[0]["telegram_id"] == "1002"


def test_admin_master_preview_is_scoped_and_cannot_manage_team(client):
    grant(client, "1001")
    foreign = create(client, "1001")
    preview = {"X-View-Mode": "master"}
    session = client.get("/api/session", headers=preview).json()
    assert session["can_switch_role"] is True and session["user"]["role"] == "master"
    assert foreign not in [item["id"] for item in session["projects"]]
    assert client.get("/api/admin/users", headers=preview).status_code == 403
    payload = {"date": today(), "revision": 0, "lines": [{"item_id": "excel-17", "quantity": 1}]}
    assert (
        client.post("/api/reports", json=payload, headers={"X-Project-Id": foreign}).status_code
        == 403
    )
    assert client.get("/api/bootstrap", headers={"X-Project-Id": foreign}).status_code == 200
    assert (
        client.get(
            "/api/session", headers={"X-Preview-User": "1001", "X-View-Mode": "admin"}
        ).json()["user"]["role"]
        == "master"
    )


def test_profile_updates_only_current_user(client):
    grant(client, "1001")
    grant(client, "1002")
    response = client.post(
        "/api/profile", json={"name": "Новое имя"}, headers={"X-Preview-User": "1001"}
    )
    assert response.status_code == 200
    assert workspaces.user("1001")["name"] == "Новое имя"
    assert workspaces.user("1002")["name"] == "Мастер"


def test_analytics_filters_isolation_totals_and_styled_export(client):
    grant(client, "1001")
    grant(client, "1002")
    first = create(client, "1001")
    second = create(client, "1002")
    for object_id, user, quantity in ((first, "1001", 10), (second, "1002", 20)):
        response = client.post(
            "/api/reports",
            json={
                "date": today(),
                "revision": 0,
                "crew_count": 5,
                "lines": [{"item_id": "excel-17", "quantity": quantity}],
            },
            headers={"X-Preview-User": user, "X-Project-Id": object_id},
        )
        assert response.status_code == 200
    query = f"?start={today()}&end={today()}"
    response = client.get("/api/analytics" + query).json()
    assert response["summary"]["amount"] == 300
    assert response["summary"]["worker_days"] == 10 and response["summary"]["per_person"] == 30
    own = client.get("/api/analytics" + query, headers={"X-Preview-User": "1001"}).json()
    assert own["summary"]["amount"] == 100
    assert (
        client.get(
            "/api/analytics?project_id=" + second, headers={"X-Preview-User": "1001"}
        ).status_code
        == 403
    )
    exported = client.get("/api/analytics/export.xlsx" + query)
    workbook = openpyxl.load_workbook(io.BytesIO(exported.content))
    assert workbook["Общий отчёт"]["A3"].value == 300
    assert workbook["Общий отчёт"].freeze_panes == "A6"
    assert workbook["Выполненные работы"]["D2"].alignment.wrap_text is True
    assert workbook["Общий отчёт"]["A5"].fill.fgColor.rgb.endswith("2563EB")
    headers = {"X-Preview-User": "1001"}
    ticket = client.get(
        "/api/analytics/export.xlsx" + query + "&prepare=true", headers=headers
    ).json()
    head = client.head(ticket["url"])
    assert head.status_code == 200 and head.content == b""
    downloaded = client.get(ticket["url"])
    assert (
        downloaded.headers["content-disposition"] == f'attachment; filename="{ticket["filename"]}"'
    )
    assert downloaded.headers["access-control-allow-origin"] == "https://web.telegram.org"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert openpyxl.load_workbook(io.BytesIO(downloaded.content))["Общий отчёт"]["A3"].value == 100
    assert client.get(ticket["url"].replace(ticket["filename"], "other.xlsx")).status_code == 404


def test_csv_download_link_expires_and_revoked_access_is_rechecked(client, monkeypatch):
    grant(client, "1001")
    project = create(client, "1001")
    headers = {"X-Preview-User": "1001", "X-Project-Id": project}
    path = "/api/export.csv?prepare=true"
    ticket = client.get(path, headers=headers).json()["url"]
    assert client.get(ticket).text.startswith("\ufeffДата;Работа;")
    monkeypatch.setattr(report_downloads, "DOWNLOAD_TTL", 0)
    expired = client.get(path, headers=headers).json()["url"]
    assert client.get(expired).status_code == 404
    with workspaces.registry() as database:
        database.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", ("1001",))
    assert client.get(ticket).status_code == 403
