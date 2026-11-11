from backend import bitrix
from test_workspaces import client, make_workbook


def test_connection_check_reads_file_without_changing_reports(client, monkeypatch):
    content = make_workbook(ambiguous=True)
    url = "https://bitrix24public.com" + "/demo.bitrix24.by/sheet/test"

    async def read_public(public_url):
        assert public_url == url
        return content, {"name": "Смета объекта.xlsx", "file_id": 161932}

    monkeypatch.setattr(bitrix, "fetch_public", read_public)
    assert client.post("/api/bitrix/connection", json={"public_url": url}).status_code == 200
    before = client.get("/api/bootstrap").json()["history"]
    response = client.post(
        "/api/bitrix/check", json={}, headers={"Origin": "http://127.0.0.1:5173"}
    )
    assert response.status_code == 200
    check = response.json()
    assert check["reachable"] is True and check["positions"] == 2
    assert any(issue.get("cell") == "B5" for issue in check["issues"])
    assert client.get("/api/bootstrap").json()["history"] == before
    assert (
        client.get("/api/bootstrap").json()["config"]["connection_check"]["name"]
        == "Смета объекта.xlsx"
    )
