import asyncio
import hashlib
import hmac
import io
import json
import time
from datetime import datetime
from urllib.parse import urlencode
import openpyxl
import pytest
from fastapi.testclient import TestClient
from backend import app as module, store, matcher, bitrix


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with TestClient(module.app) as c:
        yield c


def test_full_catalog_and_real_history(client):
    data = client.get("/api/bootstrap").json()
    assert len(data["positions"]) == 62
    copper = next(p for p in data["positions"] if p["source_row"] == 17)
    assert (copper["completed"], copper["remaining"]) == (140, 125)
    assert round(sum(h["amount"] for h in data["history"]), 2) == 1400


def test_example_is_six_exact_lines(client):
    result = client.post(
        "/api/parse",
        json={
            "text": "Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон."
        },
    ).json()
    assert [(x["item_id"], x["quantity"]) for x in result["lines"]] == [
        ("excel-17", 15),
        ("excel-18", 15),
        ("excel-20", 15),
        ("excel-21", 15),
        ("excel-55", 56),
        ("excel-44", 10),
    ]
    assert result["engine"] == "local"


def test_wrapped_worker_message_is_six_exact_project_positions(client):
    result = client.post(
        "/api/parse",
        json={
            "text": "Сегодня проложили медь 6-ку\n15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10\nхомутов под фреон"
        },
    ).json()
    assert [(line["item_id"], line["quantity"]) for line in result["lines"]] == [
        ("excel-17", 15),
        ("excel-18", 15),
        ("excel-20", 15),
        ("excel-21", 15),
        ("excel-55", 56),
        ("excel-44", 10),
    ]


def test_ambiguity_and_wrong_unit_require_choice(client):
    line = client.post("/api/parse", json={"text": "Хомуты 10 шт"}).json()["lines"][0]
    assert line["item_id"] is None and len(line["candidates"]) == 2
    line = client.post("/api/parse", json={"text": "медь 6-ка 15 кг"}).json()["lines"][0]
    assert line["item_id"] is None and "Единица" in line["reason"]


def test_search_always_returns_candidates_including_last_rows(client):
    r = client.post("/api/search", json={"text": "абсолютно непонятное название"})
    assert r.status_code == 200 and len(r.json()["suggestions"]) == 8
    r = client.post("/api/search", json={"text": "Прокладка силовых кабелей на скобах"}).json()
    assert r["suggestions"][0]["item_id"] == "excel-71"
    r = client.post("/api/search", json={"text": "кабель три на два с половиной"}).json()
    assert r["suggestions"][0]["item_id"] == "excel-55"


def test_save_replace_conflict_and_no_duplicate_aggregation(client):
    day = module.today()
    body = {
        "date": day,
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 15}],
    }
    assert client.post("/api/reports", json=body).status_code == 200
    assert client.post("/api/reports", json=body).status_code == 409
    body["revision"] = 1
    body["lines"][0]["quantity"] = 18
    assert client.post("/api/reports", json=body).status_code == 200
    data = client.get("/api/bootstrap").json()
    assert next(p for p in data["positions"] if p["id"] == "excel-17")["completed"] == 158
    assert client.get("/api/report/" + day).json()["revision"] == 2
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM audit").fetchone()[0] == 2


def test_invalid_unknown_duplicate_and_exceed_are_blocked(client):
    day = module.today()
    for qty in (0, -1, "NaN"):
        assert (
            client.post(
                "/api/reports",
                json={
                    "date": day,
                    "revision": 0,
                    "lines": [{"item_id": "excel-17", "quantity": qty}],
                },
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/reports",
            json={
                "date": day,
                "revision": 0,
                "lines": [{"item_id": "invented", "quantity": 1}],
            },
        ).status_code
        == 422
    )
    body = {
        "date": day,
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 130}],
    }
    assert client.post("/api/reports", json=body).status_code == 422
    body["allow_exceed"] = True
    assert client.post("/api/reports", json=body).status_code == 200
    body["revision"] = 1
    body["lines"] *= 2
    assert client.post("/api/reports", json=body).status_code == 422


def test_failed_remote_write_keeps_local_data_and_hides_secrets(client):
    body = {
        "date": module.today(),
        "revision": 0,
        "lines": [{"item_id": "excel-17", "quantity": 1}],
    }
    client.post("/api/reports", json=body)
    assert client.post("/api/bitrix/sync/" + module.today(), json={}).json()["ok"] is False
    assert client.get("/api/report/" + module.today()).json()["lines"] == body["lines"]
    with store.connect() as db:
        store.set_setting(db, "webhook", "secret-never-returned")
    assert "secret-never-returned" not in client.get("/api/bootstrap").text


def test_origin_rejected(client):
    assert (
        client.post(
            "/api/search",
            json={"text": "медь"},
            headers={"Origin": "https://malicious.example"},
        ).status_code
        == 403
    )


def workbook_fixture():
    w = openpyxl.Workbook()
    s = w.active
    s.title = "Работы"
    for col, value in enumerate(
        ["№", "Наименование по спецификации", "Ед изм", "К-во", "ЗП за ед."], 1
    ):
        s.cell(1, col, value)
    s.cell(3, 10, datetime(2026, 8, 19))
    s.cell(4, 2, "ОВ 3")
    s.cell(4, 10, "объем")
    for col, value in enumerate([1, "Фреонопровод медный Д6,35", "м", 100, 10], 1):
        s.cell(5, col, value)
    s.cell(5, 9, "=SUM(J5:CZ5)")
    s.cell(5, 10, 20)
    s.cell(5, 8, "=I5*E5")
    s.cell(7, 2, "ИТОГО")
    s.cell(7, 8, "=SUM(H5:H6)")
    s["B5"].font = openpyxl.styles.Font(bold=True)
    b = io.BytesIO()
    w.save(b)
    return b.getvalue()


def test_workbook_patch_preserves_formulas_and_replaces_date():
    original = workbook_fixture()
    catalog = bitrix.read_workbook(original)["positions"]
    lines = [{"item_id": "excel-5", "quantity": 12}]
    patched = bitrix.patch_workbook(original, "2026-11-10", lines, catalog)
    w = openpyxl.load_workbook(io.BytesIO(patched))
    s = w.active
    assert s["J5"].value == 20 and s["K5"].value == 12
    assert s["I5"].value == "=SUM(J5:CZ5)" and s["H7"].value == "=SUM(H5:H6)"
    assert s["B5"].font.bold and s["K3"].value == datetime(2026, 11, 10)
    twice = bitrix.patch_workbook(
        patched, "2026-11-10", [{"item_id": "excel-5", "quantity": 17}], catalog
    )
    s = openpyxl.load_workbook(io.BytesIO(twice)).active
    assert s["K5"].value == 17 and s["L3"].value is None


def test_workbook_changed_structure_rejected():
    original = workbook_fixture()
    catalog = bitrix.read_workbook(original)["positions"]
    catalog[0]["name"] = "Old name"
    with pytest.raises(ValueError, match="изменилась"):
        bitrix.patch_workbook(original, "2026-11-10", [], catalog)


def test_ai_uses_complete_catalog_and_rejects_fabricated_ids(client, monkeypatch):
    seen = {}

    async def complete(system, text, settings):
        seen["system"] = system
        return {
            "suggestions": [
                {"item_id": "invented", "reason": "fake"},
                {"item_id": "excel-71", "reason": "по смыслу"},
            ]
        }

    monkeypatch.setattr(matcher, "complete", complete)
    with store.connect() as db:
        store.set_setting(db, "llm_api_key", "test-only")
    result = client.post("/api/search", json={"text": "на скобах"}).json()
    assert result["engine"] == "llm" and [x["item_id"] for x in result["suggestions"]] == [
        "excel-71"
    ]
    assert "excel-5" in seen["system"] and "excel-71" in seen["system"]


def test_ai_failure_still_returns_options(client, monkeypatch):
    async def failure(*args):
        raise ValueError("Invalid provider output")

    monkeypatch.setattr(matcher, "complete", failure)
    with store.connect() as db:
        store.set_setting(db, "llm_api_key", "test-only")
    result = client.post("/api/search", json={"text": "изоляция"}).json()
    assert len(result["suggestions"]) == 8 and result["engine"] == "local"


def test_telegram_hash_expiry_and_allowlist(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 123})}
    secret = hmac.new(b"WebAppData", b"token", hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret,
        "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert module.validate_init_data(urlencode(data))
    data["auth_date"] = "1"
    assert not module.validate_init_data(urlencode(data))
