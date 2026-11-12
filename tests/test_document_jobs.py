import asyncio
import io

import pytest
from pypdf import PdfWriter

from backend.documents import extraction, repository, worker
from test_workspaces import client, grant


def sample_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_document_queue_ownership_ocr_ai_and_export(client, monkeypatch, tmp_path):
    grant(client, "7101")
    grant(client, "7102")
    owner = {"X-Preview-User": "7101"}
    other = {"X-Preview-User": "7102"}
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    response = client.post(
        "/api/documents",
        headers=owner,
        files={"file": ("project.pdf", sample_pdf(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    ident = response.json()["id"]
    assert client.get("/api/documents", headers=other).json() == []
    assert client.get("/api/documents/" + ident, headers=other).status_code == 404
    assert (
        client.post(
            "/api/documents/" + ident + "/analyse", headers=owner, json={"pages": [1]}
        ).status_code
        == 409
    )
    monkeypatch.setattr(worker, "ocr_page", lambda *args: None)
    assert worker.run_once()
    assert client.get("/api/documents/" + ident, headers=owner).json()["status"] == "needs_ocr"
    assert (
        client.post("/api/documents/" + ident + "/retry", headers=owner, json={}).status_code == 200
    )
    monkeypatch.setattr(
        worker,
        "ocr_page",
        lambda *args: "Спецификация: труба медная, диаметр 6 мм, количество 10 м.",
    )
    assert worker.run_once()
    job = client.get("/api/documents/" + ident, headers=owner).json()
    assert job["status"] == "text_ready" and job["processed"] == 1
    assert (
        client.post(
            "/api/documents/" + ident + "/analyse", headers=owner, json={"pages": [999]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/documents/" + ident + "/analyse", headers=owner, json={"pages": [1]}
        ).status_code
        == 200
    )
    monkeypatch.setattr(worker.matcher, "provider", lambda *args: {"key": "test"})

    async def complete(*args):
        return {
            "works": [
                {
                    "name": "Прокладка медной трубы",
                    "category": "Кондиционирование",
                    "unit": "м",
                    "quantity": 10,
                    "quote": "труба медная, диаметр 6 мм, количество 10 м.",
                    "notes": "Уточнить высоту",
                }
            ],
            "questions": ["На какой высоте выполнять работы?"],
        }

    monkeypatch.setattr(worker.matcher, "complete", complete)
    assert worker.run_once()
    result = client.get("/api/documents/" + ident, headers=owner).json()
    assert result["status"] == "draft"
    assert result["payload"]["works"][0]["quantity"] == 10
    assert result["payload"]["works"][0]["confirmed"] is False
    exported = client.get("/api/documents/" + ident + "/export.xlsx", headers=owner)
    assert exported.status_code == 200
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(exported.content))
    assert book.active["H2"].value == "Уточнить высоту"
    assert book.active["F2"].value is None
    assert client.get("/api/documents/" + ident + "/export.xlsx", headers=other).status_code == 404


@pytest.mark.parametrize(
    "filename,content", [("bad.pdf", b"not a PDF"), ("empty.pdf", b""), ("data.txt", b"%PDF-")]
)
def test_invalid_document_upload(client, monkeypatch, tmp_path, filename, content):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    response = client.post("/api/documents", files={"file": (filename, content)})
    assert response.status_code == 422
    assert not client.get("/api/documents").json()


def test_ai_cannot_return_unquoted_work_or_invent_quantity(monkeypatch):
    async def complete(*args):
        return {
            "works": [
                {"name": "Придуманная работа", "quote": "нет такой цитаты", "quantity": 0},
                {
                    "name": "Монтаж трубы",
                    "quote": "Труба: количество 12 м",
                    "quantity": 99,
                    "unit": "м",
                },
            ]
        }

    monkeypatch.setattr(extraction.matcher, "complete", complete)
    works, _ = asyncio.run(extraction.propose("Труба: количество 12 м", 1, {}))
    assert len(works) == 1 and works[0]["quantity"] is None
