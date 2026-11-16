import base64
import io
import json

import httpx
import openpyxl
from test_workspaces import client, create, grant  # noqa: F401 - pytest fixture

from backend import bitrix, store, tables, workspaces
from backend.clock import today
from backend.documents.structured import candidates
from backend.workbook_journal import format_journal


def test_expenses_sync_separately_and_survive_daily_report(client, monkeypatch):  # noqa: F811
    grant(client, "1752")
    project = create(client, "1752", sample=False)
    headers = {"X-Preview-User": "1752", "X-Project-Id": project}
    positions = [
        {
            "id": "duct",
            "name": "Монтаж воздуховода",
            "section": "Вентиляция",
            "unit": "м",
            "planned": 20,
            "rate": 17,
            "baseline": 1,
            "source_row": 5,
            "source_sheet": "Журнал работ",
        },
        {
            "id": "fuel",
            "name": "Топливо",
            "section": "ДОП",
            "unit": "л",
            "planned": 40,
            "rate": 2,
            "baseline": 0,
            "source_row": 6,
            "source_sheet": "Журнал работ",
        },
    ]
    original = io.BytesIO()
    openpyxl.Workbook().save(original)
    remote = {"bytes": format_journal(original.getvalue(), positions, [], {}, []), "writes": 0}
    mappings, _ = tables.discover(remote["bytes"])
    info = workspaces.project(workspaces.user("1752"), project)
    with store.connect(info["db_path"]) as db:
        for position in positions:
            store.insert_position(db, position)
        store.set_setting(db, "source", "bitrix")
        store.set_setting(db, "webhook", "https://demo.bitrix24.by/rest/1/abc123/")
        store.set_setting(db, "file_id", "9")
        store.set_setting(db, "sheet_mappings", json.dumps(mappings))

    async def download(*args):
        return remote["bytes"], {"NAME": "estimate.xlsx"}

    async def rest(webhook, method, body):
        assert method == "disk.file.uploadVersion"
        remote["bytes"] = base64.b64decode(body["fileContent"][1])
        remote["writes"] += 1
        if remote["writes"] == 1:
            raise httpx.ReadTimeout("Response lost after upload")
        return {"ID": 9}

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", rest)
    url = "/api/object/expenses"
    assert [row["id"] for row in client.get(url, headers=headers).json()["templates"]] == ["fuel"]
    assert [
        row["extra"] for row in client.get("/api/bootstrap", headers=headers).json()["positions"]
    ] == [False, True]
    body = {"date": today(), "name": "Топливо", "unit": "л", "quantity": "10", "rate": "2.32"}
    saved = client.post(url, headers=headers, json=body).json()
    assert saved["sync_status"] == "pending" and saved["total"] == "23.20"
    resent = client.post(url + "/sync", headers=headers).json()
    assert resent["sync_status"] == "synced" and remote["writes"] == 1
    [row] = resent["rows"]
    edited = client.post(
        url,
        headers=headers,
        json={**body, "id": row["id"], "revision": row["revision"], "quantity": "5"},
    ).json()
    assert edited["sync_status"] == "synced" and edited["total"] == "11.60"
    assert (
        client.post(url, headers=headers, json={**body, "id": row["id"], "revision": 1}).status_code
        == 409
    )
    draft = {"date": today(), "revision": 0, "lines": [{"item_id": "fuel", "quantity": 1}]}
    assert client.post("/api/reports", headers=headers, json=draft).status_code == 409
    draft["lines"] = [{"item_id": "duct", "quantity": 2}]
    report = client.post("/api/reports", headers=headers, json=draft).json()
    assert report["sync_status"] == "synced", report
    assert report["payroll"]["amount"] == 34
    workbook = openpyxl.load_workbook(io.BytesIO(remote["bytes"]), data_only=True)
    assert workbook["Доп. расходы"]["F2"].value == 11.6
    journal = workbook["Журнал работ"]
    grand_total = next(
        cell.row for cell in journal["B"] if cell.value == "Итого затраты по объекту"
    )
    assert journal.cell(grand_total, 8).value == 62.6
    assert journal.row_dimensions[6].hidden


def test_pdf_skips_expense_section_and_fuel(tmp_path):
    table = (
        "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество |\n"
        "Строка 2: C1–C2=ДОП |\n"
        "Строка 3: C1–C2=Пробивка отверстий | C2–C3=шт. | C3–C4=7 |\n"
        "Строка 4: C1–C2=Вентиляция |\n"
        "Строка 5: C1–C2=Топливо | C2–C3=л | C3–C4=10 |\n"
        "Строка 6: C1–C2=Монтаж воздуховодов | C2–C3=м² | C3–C4=15 |"
    )
    records = tmp_path / "docling"
    records.mkdir()
    (records / "page-1.json").write_text(
        json.dumps({"source": "test", "text": table, "analysis_text": table}), encoding="utf-8"
    )
    works, controls = candidates(tmp_path, {"file_hash": "test"})
    assert [(row["source_row"], row["quantity_cell"]) for row in works] == [(6, "15")]
    assert not controls
