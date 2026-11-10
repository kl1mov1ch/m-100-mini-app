import base64
import io
import json
from datetime import datetime

import openpyxl

from backend import bitrix, store, workspaces
from backend.imports import directory
from test_workspaces import client, create, make_workbook


def preview_table(client):
    project_id = create(client, sample=False)
    workbook = openpyxl.load_workbook(io.BytesIO(make_workbook(ambiguous=True)))
    sheet = workbook["Монтаж"]
    sheet["E3"] = datetime(2026, 8, 19)
    sheet["F3"] = datetime(2026, 8, 19)
    sheet["E4"] = 10
    sheet["F4"] = 5
    stream = io.BytesIO()
    workbook.save(stream)
    content = stream.getvalue()
    result = client.post(
        "/api/imports/upload",
        files={
            "file": (
                "work.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers={"X-Project-Id": project_id},
    )
    assert result.status_code == 200
    return project_id, result.json(), content


def test_correct_cells_and_merge_duplicate_dates(client):
    project_id, preview, original = preview_table(client)
    response = client.post(
        "/api/imports/edit",
        json={
            "token": preview["token"],
            "edits": [{"sheet": "Монтаж", "cell": "B5", "value": 3.5}],
            "duplicates": [{"sheet": "Монтаж", "date": "2026-08-19", "strategy": "sum"}],
        },
        headers={"X-Project-Id": project_id},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["saved_to_source"] is False
    assert not any(warning.get("cell") == "B5" for warning in result["warnings"])
    assert not any("duplicate-dates" in warning["id"] for warning in result["warnings"])
    updated = openpyxl.load_workbook(directory() / f"{preview['token']}.xlsx")
    assert updated["Монтаж"]["E4"].value == 15
    assert updated["Монтаж"]["F4"].value is None
    assert updated["Монтаж"]["F3"].value is None
    assert updated["Монтаж"]["B5"].value == 3.5


def test_bitrix_cell_correction_uploads_and_verifies_version(client, monkeypatch):
    project_id, preview, original = preview_table(client)
    meta_path = directory() / f"{preview['token']}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["source"] = "bitrix"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    project = workspaces.project(workspaces.user("local-admin"), project_id)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "webhook", "test-connection")
    uploaded = []

    async def download(*args):
        return (uploaded[-1] if uploaded else original), {"NAME": "work.xlsx"}

    async def upload(webhook, method, payload):
        assert method == "disk.file.uploadVersion"
        uploaded.append(base64.b64decode(payload["fileContent"][1]))
        return {"ID": 161932}

    monkeypatch.setattr(bitrix, "download_rest", download)
    monkeypatch.setattr(bitrix, "rest", upload)
    response = client.post(
        "/api/imports/edit",
        json={"token": preview["token"], "edits": [{"sheet": "Монтаж", "cell": "B5", "value": 4}]},
        headers={"X-Project-Id": project_id, "Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["saved_to_source"] is True
    assert openpyxl.load_workbook(io.BytesIO(uploaded[0]))["Монтаж"]["B5"].value == 4


def test_source_edits_without_write_permission_are_explicit(client):
    project_id, preview, original = preview_table(client)
    meta_path = directory() / f"{preview['token']}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["source"] = "bitrix"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    response = client.post(
        "/api/imports/edit",
        json={"token": preview["token"], "edits": [{"sheet": "Монтаж", "cell": "B5", "value": 4}]},
        headers={"X-Project-Id": project_id},
    )
    assert response.status_code == 400 and "вебхук" in response.json()["detail"]
