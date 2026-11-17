import io
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx
import openpyxl
from test_workspaces import client as client
from test_workspaces import create, grant

from backend import notifications, report_downloads, store, workspaces
from backend.clock import today


def test_reminders_only_target_missing_reports_and_deduplicate(client, monkeypatch):
    for user in ("1001", "1002", "1003", "1004"):
        grant(client, user)
    submitted = create(client, "1001")
    create(client, "1002")
    create(client, "1003", sample=False)
    imported = create(client, "1004")
    source = workspaces.project(workspaces.user("1004"), imported)
    with store.connect(source["db_path"]) as database:
        database.execute(
            "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
            ("excel-17", today(), 5),
        )
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


def test_reminders_address_selected_users_or_everyone_with_the_entered_text(client, monkeypatch):
    for ident in ("1001", "1002", "1003"):
        grant(client, ident)
    with workspaces.registry() as database:
        database.execute(
            "INSERT INTO users(telegram_id,name,role,enabled) VALUES(?,?,'admin',1)",
            ("1004", "Администратор"),
        )
        database.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", ("1003",))
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    sent = []

    def telegram(request):
        sent.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        notifications.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(telegram)),
    )
    body = {
        "request_id": str(uuid.uuid4()),
        "audience": "selected",
        "recipient_ids": ["1002", "1002", "1003"],
        "text": "Проверьте расписание\nСпасибо!",
    }
    response = client.post("/api/admin/reminders/send", json=body)
    assert response.json()["sent"] == 1
    assert sent[0]["chat_id"] == ["1002"]
    assert sent[0]["text"] == [body["text"]]
    assert client.post("/api/admin/reminders/send", json=body).json()["skipped"] == 1
    assert (
        client.post(
            "/api/admin/reminders/send",
            json={**body, "recipient_ids": []},
        ).status_code
        == 422
    )
    response = client.post(
        "/api/admin/reminders/send",
        json={**body, "request_id": str(uuid.uuid4()), "audience": "all"},
    )
    active_ids = {user["telegram_id"] for user in notifications.telegram_users()}
    assert {"1001", "1002", "1004"} <= active_ids
    assert "1003" not in active_ids
    assert response.json()["sent"] == len(active_ids)
    assert {entry["chat_id"][0] for entry in sent[1:]} == active_ids


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
    first = create(client, "1001", name="Объект А")
    second = create(client, "1002", name="Объект Б")
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
    first_day = date.fromisoformat(today()) - timedelta(days=1)
    first_project = workspaces.project(workspaces.user("1001"), first)
    with store.connect(first_project["db_path"]) as database:
        database.execute("UPDATE positions SET planned=12,baseline=0 WHERE id=?", ("excel-17",))
        database.execute("DELETE FROM entries WHERE item_id=? AND date<?", ("excel-17", today()))
        database.execute(
            "INSERT INTO entries(item_id,date,quantity) VALUES(?,?,?)",
            ("excel-17", first_day.isoformat(), 3),
        )
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
    assert workbook.sheetnames == ["Работы по дням", "Графики"]
    sheet = workbook["Работы по дням"]
    assert sheet.freeze_panes == "C5"
    assert sheet["G4"].value.date().isoformat() == today()
    assert sheet["E5"].value == sheet["G5"].value == 300
    assert sheet["E6"].value == sheet["G6"].value == 10
    actual = next(row for row in sheet if row[6].value == 10 and row[3].value == 12)
    assert actual[4].value == 10 and actual[5].value == 1
    assert actual[5].fill.fgColor.rgb.endswith("FCE2E3")
    assert actual[6].font.color.rgb.endswith("9F2028")
    charts = workbook["Графики"]
    assert len(charts._charts) == 3
    assert len({chart.anchor._from.row for chart in charts._charts}) == 3
    assert all(chart.anchor.ext.cx >= 25 * 360_000 for chart in charts._charts)
    assert charts["AB2"].value == 300 and charts["AC2"].value == 10
    assert 0 <= charts["AD2"].value <= 1
    wider = client.get(f"/api/analytics/export.xlsx?start={first_day}&end={today()}")
    wider_book = openpyxl.load_workbook(io.BytesIO(wider.content))
    assert wider_book.active["G4"].value.date() == first_day
    assert wider_book.active["H4"].value.date().isoformat() == today()
    assert wider_book.active["G6"].value is None
    earlier_work = next(
        row for row in wider_book.active if row[6].value == 3 and row[7].value == 10
    )
    assert not earlier_work[6].fill.fgColor.rgb.endswith("FCE2E3")
    assert earlier_work[7].fill.fgColor.rgb.endswith("FCE2E3")
    headers = {"X-Preview-User": "1001"}
    ticket = client.get(
        "/api/analytics/export.xlsx" + query + "&prepare=true", headers=headers
    ).json()
    assert "Отчёт_" in ticket["filename"]
    assert today() in ticket["filename"]
    head = client.head(ticket["url"])
    assert head.status_code == 200 and head.content == b""
    downloaded = client.get(ticket["url"])
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    assert downloaded.headers["access-control-allow-origin"] == "https://web.telegram.org"
    assert downloaded.headers["cache-control"] == "private, no-store"
    owned_sheet = openpyxl.load_workbook(io.BytesIO(downloaded.content)).active
    assert owned_sheet["G6"].value == 100
    assert "Объект Б" not in {row[0].value for row in owned_sheet}
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
