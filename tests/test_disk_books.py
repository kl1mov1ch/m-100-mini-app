import base64
import io
from datetime import timedelta

import httpx
import openpyxl
from test_workspaces import client, create, grant  # noqa: F401 - pytest fixture

from backend import bitrix, bitrix_disk, imports, matcher, store, workspaces
from backend.clock import today


def disk(monkeypatch):
    files = {}
    calls = []
    folder = {}
    fail_after_upload = set()

    def details(ident):
        entry = files[ident]
        return {
            "ID": ident,
            "NAME": entry[0],
            "DETAIL_URL": f"https://demo.bitrix24.by/company/personal/user/1/disk/file/{ident}",
        }

    async def rest(webhook, method, body):
        calls.append(method)
        if method == "disk.storage.getList":
            return [{"ID": 17, "ENTITY_ID": "1", "ENTITY_TYPE": "user"}]
        if method == "disk.storage.getChildren":
            return list(folder.values())
        if method == "disk.storage.addFolder":
            entry = {"ID": 21, "TYPE": "folder", "NAME": body["data"]["NAME"]}
            folder[21] = entry
            return entry
        if method == "disk.folder.getChildren":
            return [
                details(ident)
                for ident in files
                if details(ident)["NAME"] == body["filter"]["NAME"]
            ]
        if method in ("disk.folder.uploadFile", "disk.file.uploadVersion"):
            ident = len(files) + 30 if method == "disk.folder.uploadFile" else body["id"]
            name, encoded = body["fileContent"]
            files[ident] = (name, base64.b64decode(encoded))
            if name in fail_after_upload:
                fail_after_upload.remove(name)
                raise httpx.ReadTimeout("Response interrupted")
            return details(ident)
        if method == "disk.file.get":
            return details(body["id"])
        raise AssertionError(method)

    async def download(webhook, ident):
        return files[ident][1], details(ident)

    monkeypatch.setattr(bitrix, "rest", rest)
    monkeypatch.setattr(bitrix, "download_rest", download)
    return files, calls, fail_after_upload


def owner(client, sample=True):
    grant(client, "1850")
    project = create(client, "1850", sample=sample)
    headers = {"X-Preview-User": "1850", "X-Project-Id": project}
    hook = client.post(
        "/api/profile/disk-webhooks",
        headers=headers,
        json={
            "name": "Диск",
            "url": "https://demo.bitrix24.by/rest/1/testFakeKey1/",
        },
    ).json()["id"]
    return project, headers, hook


def test_create_blank_disk_book_and_connect_after_review(client, monkeypatch):  # noqa: F811
    async def no_journal(*args):
        return {}

    monkeypatch.setattr(imports, "write_journal", no_journal)
    files, calls, _ = disk(monkeypatch)
    project, headers, hook = owner(client, sample=False)
    with store.connect(workspaces.project(workspaces.user("1850"), project)["db_path"]) as db:
        store.set_setting(db, "source", "file")
    target = {"name": "Новая смета.xlsx", "webhook_id": hook}
    created = client.post("/api/bitrix/disk-book", headers=headers, json=target)
    assert created.status_code == 200, created.text
    ident = created.json()["id"]
    assert client.post("/api/bitrix/disk-book", headers=headers, json=target).json()["id"] == ident
    assert calls.count("disk.folder.uploadFile") == 1
    blank = client.post("/api/imports/disk-book", headers=headers)
    assert (
        blank.status_code == 422
        and client.get("/api/bootstrap", headers=headers).json()["config"]["source"] == "file"
    )

    workbook = openpyxl.load_workbook(io.BytesIO(files[ident][1]))
    workbook.active.append(["Установка решётки Ø160", "шт.", 20, 15, "Вентиляция"])
    data = io.BytesIO()
    workbook.save(data)
    files[ident] = (target["name"], data.getvalue())
    response = client.post("/api/imports/disk-book", headers=headers)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert client.get("/api/bootstrap", headers=headers).json()["config"]["source"] == "file"
    confirm = client.post(
        "/api/imports/confirm",
        headers=headers,
        json={
            "token": preview["token"],
            "sheets": preview["sheets"],
            "acknowledged": [warning["id"] for warning in preview["warnings"]],
        },
    )
    assert confirm.status_code == 200, confirm.text
    config = client.get("/api/bootstrap", headers=headers).json()["config"]
    assert config["source"] == "bitrix" and config["file_id"] == ident


def test_cumulative_file_keeps_days_notes_and_retries_without_duplicate(client, monkeypatch):  # noqa: F811
    from datetime import date

    files, calls, fail = disk(monkeypatch)
    _, headers, hook = owner(client)
    assert client.post(
        "/api/bitrix/report-files", headers=headers, json={"webhook_id": hook}
    ).is_success
    day = today()
    earlier = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    endpoint = "/api/reports"
    first = {
        "date": earlier,
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 2}],
        "crew_count": 3,
    }
    fail.add(bitrix_disk.REPORT_FILE)
    initial = client.post(endpoint, headers=headers, json=first)
    assert initial.status_code == 200 and initial.json()["sync_status"] == "pending"
    retry = client.post("/api/bitrix/sync/" + earlier, headers=headers).json()
    assert retry["ok"], retry
    second = {
        "date": day,
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 1, "note": "Готов второй этаж"}],
        "day_note": "Доступ после 08:00",
        "crew_count": 2,
    }
    assert client.post(endpoint, headers=headers, json=second).json()["sync_status"] == "synced"
    assert calls.count("disk.folder.uploadFile") == 1
    assert calls.count("disk.file.uploadVersion") == 1
    assert (
        client.post(
            endpoint,
            headers=headers,
            json={**second, "revision": 1, "day_note": "Доступ после 09:00"},
        ).json()["sync_status"]
        == "synced"
    )
    [(filename, content)] = files.values()
    assert filename == bitrix_disk.REPORT_FILE
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    assert workbook.sheetnames == ["Работы по дням", "Примечания"]
    sheet = workbook.active
    dates = [cell.value.date().isoformat() for cell in sheet[4][6:]]
    assert dates == sorted(set(dates)) and dates[-2:] == [earlier, day]
    values = {cell.value for tab in workbook for row in tab for cell in row if cell.value is not None}
    assert {"Доступ после 09:00", "Готов второй этаж", "Выработка", "Человек за день"} <= values
    assert "Доступ после 08:00" not in values
    assert any(
        cell.comment and cell.comment.text == "Готов второй этаж" for row in sheet for cell in row
    )


def test_polish_note_keeps_numeric_values(client, monkeypatch):  # noqa: F811
    _, headers, _ = owner(client, sample=False)
    monkeypatch.setattr(matcher, "provider", lambda _: {"key": "test"})

    async def complete(*args):
        return {"text": "Вентиляторы в количестве 12 шт."}

    monkeypatch.setattr(matcher, "complete", complete)
    result = client.post(
        "/api/object/polish-note", headers=headers, json={"text": "вентиляторы 2 шт"}
    )
    assert result.status_code == 200 and result.json() == {
        "text": "Вентиляторы 2 шт.",
        "engine": "local",
    }


def test_polish_applies_punctuation_when_ai_echoes_text(monkeypatch):
    import asyncio

    from backend.report_notes import polish

    original = "в течении смены монтаж закончили но 2,5 м осталось\n\nсдесь нужен доступ"

    async def echo(*args):
        return {"text": original}

    monkeypatch.setattr(matcher, "complete", echo)
    assert asyncio.run(polish(original, {"llm_api_key": "test"})) == {
        "text": "В течение смены монтаж закончили, но 2,5 м осталось.\n\nЗдесь нужен доступ.",
        "engine": "local",
    }


def test_polish_accepts_grammar_and_sentence_rewrite(monkeypatch):
    import asyncio

    from backend.report_notes import polish

    original = "на втором этажи смантировали 2 клапана потом доступ нам не дали"
    edited = "На втором этаже смонтировали 2 клапана. Затем нам не предоставили доступ."
    requests = []

    async def complete(prompt, text, settings):
        requests.append(prompt)
        return {"text": original if len(requests) == 1 else edited}

    monkeypatch.setattr(matcher, "complete", complete)
    assert asyncio.run(polish(original, {"llm_api_key": "test"})) == {
        "text": edited,
        "engine": "ai",
    }
    assert len(requests) == 2 and "грамматику" in requests[1]
