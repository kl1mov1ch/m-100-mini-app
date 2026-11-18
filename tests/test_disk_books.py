import base64
import io
from datetime import timedelta

import httpx
import openpyxl
from test_workspaces import client, create, grant  # noqa: F401 - pytest fixture

from backend import bitrix, bitrix_disk, matcher, store, workspaces
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
        if method == "disk.folder.addFolder":
            folder[22] = {"ID": 22, "TYPE": "folder", "NAME": body["data"]["NAME"]}
            return folder[22]
        if method == "disk.file.getExternalLink":
            return "https://demo.bitrix24.by/~Example"
        if method == "disk.folder.getChildren" and body["id"] == 21 and 22 in folder:
            return [folder[22]]
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


def test_create_disk_book_connects_and_retries_without_duplicates(client, monkeypatch):  # noqa: F811
    files, calls, fail = disk(monkeypatch)
    project, headers, hook = owner(client)
    day = today()
    report = {
        "date": day,
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 2}],
        "crew_count": 3,
        "day_note": "Смена завершена",
    }
    assert client.post("/api/reports", headers=headers, json=report).is_success
    target = {"name": "Новая смета.xlsx", "work_type": "Монтаж", "webhook_id": hook}
    endpoint = "/api/bitrix/disk-book"
    fail.add("Отчётность проекта.xlsx")
    assert client.post(endpoint, headers=headers, json=target).status_code == 502
    created = client.post(endpoint, headers=headers, json=target)
    assert created.is_success, created.text
    item = created.json()
    assert item["folder_name"] == "Новая смета" and item["work_type"] == "Монтаж"
    assert item["share_url"] == "https://demo.bitrix24.by/~Example"
    assert client.post(endpoint, headers=headers, json=target).json() == item
    assert calls.count("disk.folder.uploadFile") == 1
    workbook = openpyxl.load_workbook(io.BytesIO(files[item["id"]][1]))
    assert workbook.properties.identifier == "M-100:" + project
    assert any(c.data_type == "f" for row in workbook.active for c in row)
    parsed = bitrix.read_workbook(files[item["id"]][1], generated_only=True)
    assert any(p["id"] == "excel-17" for p in parsed["positions"])
    assert any(
        e["item_id"] == "excel-17" and e["date"] == day and e["quantity"] == 2
        for e in parsed["entries"]
    )
    assert parsed["crew_by_day"][day] == 3
    assert "Примечания" in workbook.sheetnames
    config = client.get("/api/bootstrap", headers=headers).json()["config"]
    assert (config["source"], config["file_id"], config["journal_status"]) == (
        "bitrix",
        item["id"],
        "ready",
    )
    assert client.post("/api/bitrix/check", headers=headers).json()["structure_valid"]
    edited = client.post(
        "/api/reports",
        headers=headers,
        json={**report, "revision": 1, "lines": [{"item_id": "excel-17", "quantity": 3}]},
    )
    assert edited.is_success and edited.json()["sync_status"] == "synced", edited.text
    after = bitrix.read_workbook(files[item["id"]][1], generated_only=True)
    assert any(e["item_id"] == "excel-17" and e["quantity"] == 3 for e in after["entries"])


def test_new_project_has_dated_empty_journal_when_public_links_disabled(client, monkeypatch):  # noqa: F811
    files, _, _ = disk(monkeypatch)
    original = bitrix.rest

    async def restricted(webhook, method, body):
        if method == "disk.file.getExternalLink":
            raise ValueError("ACCESS_DENIED")
        return await original(webhook, method, body)

    monkeypatch.setattr(bitrix, "rest", restricted)
    _, headers, hook = owner(client, sample=False)
    result = client.post(
        "/api/bitrix/disk-book", headers=headers, json={"name": "Школа", "webhook_id": hook}
    )
    assert result.is_success, result.text
    meta = result.json()
    assert meta["share_url"] == ""
    content = files[meta["id"]][1]
    parsed = bitrix.read_workbook(content, generated_only=True)
    assert parsed["positions"] == [] and parsed["entries"] == []
    assert (
        openpyxl.load_workbook(io.BytesIO(content)).active["J3"].value.date().isoformat() == today()
    )
    assert client.post("/api/bitrix/check", headers=headers).json()["structure_valid"]


def test_uploaded_estimate_keeps_original_sheets_and_work_ids(client, monkeypatch):  # noqa: F811
    from test_workspaces import make_workbook

    files, _, _ = disk(monkeypatch)
    _, headers, hook = owner(client, sample=False)
    original = make_workbook(False, True)
    upload = client.post(
        "/api/imports/upload", headers=headers, files={"file": ("Смета.xlsx", original)}
    )
    assert upload.is_success, upload.text
    preview = upload.json()
    confirmed = client.post(
        "/api/imports/confirm",
        headers=headers,
        json={
            "token": preview["token"],
            "sheets": preview["sheets"],
            "acknowledged": [w["id"] for w in preview["warnings"]],
        },
    )
    assert confirmed.is_success, confirmed.text
    created = client.post(
        "/api/bitrix/disk-book", headers=headers, json={"name": "Школа", "webhook_id": hook}
    )
    assert created.is_success, created.text
    content = files[created.json()["id"]][1]
    saved = openpyxl.load_workbook(io.BytesIO(content))
    source = openpyxl.load_workbook(io.BytesIO(original))
    for sheet in source:
        assert tuple(saved[sheet.title].values) == tuple(sheet.values)
    parsed = bitrix.read_workbook(content, generated_only=True)

    def catalogue(rows):
        return {(r["id"], r["name"], r["rate"], r["planned"]) for r in rows}

    assert catalogue(parsed["positions"]) == catalogue(preview["positions"])


def test_foreign_file_stays_untouched(client, monkeypatch):  # noqa: F811
    files, calls, _ = disk(monkeypatch)
    _, headers, hook = owner(client)
    before = io.BytesIO()
    openpyxl.Workbook().save(before)
    files[77] = ("Отчётность проекта.xlsx", before.getvalue())
    created = client.post(
        "/api/bitrix/disk-book", headers=headers, json={"name": "Школа", "webhook_id": hook}
    )
    assert created.status_code == 409
    assert files[77][1] == before.getvalue() and "disk.file.uploadVersion" not in calls
    assert client.get("/api/bootstrap", headers=headers).json()["config"]["source"] != "bitrix"


def test_share_link_is_checked_against_connected_file(client, monkeypatch):  # noqa: F811
    files, _, _ = disk(monkeypatch)
    _, headers, hook = owner(client, sample=False)
    meta = client.post(
        "/api/bitrix/disk-book", headers=headers, json={"name": "Магазин", "webhook_id": hook}
    ).json()
    ident = meta["id"]

    async def public(url):
        return files[ident][1], {"file_id": ident if url.endswith("correct") else ident + 1}

    monkeypatch.setattr(bitrix, "fetch_public", public)
    endpoint = "/api/bitrix/disk-book/share-link"
    link = "https://bitrix24public.com/demo.bitrix24.by/sheet/"
    assert client.post(endpoint, headers=headers, json={"url": link + "other"}).status_code == 422
    assert (
        client.post(endpoint, headers=headers, json={"url": link + "correct"}).json()["share_url"]
        == link + "correct"
    )


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
    values = {
        cell.value for tab in workbook for row in tab for cell in row if cell.value is not None
    }
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
