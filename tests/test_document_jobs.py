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
    assert job["status"] == "ai_queued" and job["processed"] == 1
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
    assert result["status"] == "needs_review"
    assert result["payload"]["works"][0]["quantity"] == 10
    assert result["payload"]["works"][0]["confirmed"] is False
    exported = client.get("/api/documents/" + ident + "/export.xlsx", headers=owner)
    assert exported.status_code == 200
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(exported.content))
    assert book.active["H2"].value == "Уточнить высоту"
    assert book.active["F2"].value is None
    assert client.get("/api/documents/" + ident + "/export.xlsx", headers=other).status_code == 404
    assert (
        client.get("/api/documents/" + ident + "/export.xlsx?final=true", headers=owner).status_code
        == 409
    )
    group = result["payload"]["groups"][0]
    body = {"version": result["updated_at"], "quantity": "10", "rate": "12.345", "unit": "м"}
    route = "/api/documents/" + ident + "/groups/" + group["id"]
    assert client.post(route, headers=other, json=body).status_code == 404
    assert client.post(route, headers=owner, json={**body, "rate": "NaN"}).status_code == 422
    assert client.post(route, headers=owner, json={**body, "unit": "см"}).status_code == 422
    first = client.post(route, headers=owner, json=body)
    assert first.status_code == 200, first.text
    reviewed = first.json()
    assert reviewed["payload"]["summary"]["amount"] == 123.45
    assert reviewed["status"] == "needs_review"
    assert client.post(route, headers=owner, json=body).status_code == 409
    accepted = client.post(
        route,
        headers=owner,
        json={**body, "version": reviewed["updated_at"], "acknowledge_scope": True},
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "ready"
    final = client.get("/api/documents/" + ident + "/export.xlsx?final=true", headers=owner)
    assert final.status_code == 200
    book = openpyxl.load_workbook(io.BytesIO(final.content))
    assert book.active["G2"].value == 123.45


def test_review_batch_is_atomic_and_duplicate_resolution_is_explicit(client, monkeypatch, tmp_path):
    from backend.documents.normalization import build_groups

    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    work = {
        "name": "Монтаж трубы",
        "category": "Вентиляция",
        "unit": "м",
        "quantity": 10,
        "page": 1,
        "quote": "П1: труба 10 м",
    }
    groups = build_groups([work, {**work, "page": 2, "quote": "П1 спецификация: труба 10 м"}])
    job = repository.create("local-admin", "test.pdf")
    job.status = "needs_review"
    job.payload = {"groups": groups, "coverage": {"complete": True}}
    with repository.session() as database:
        database.add(job)
        database.flush()
    loaded = client.get("/api/documents/" + job.id).json()
    body = {
        "version": loaded["updated_at"],
        "items": [{"group_id": groups[0]["id"], "quantity": "10", "rate": "2", "unit": "м"}],
    }
    route = "/api/documents/" + job.id + "/review"
    assert client.post(route, json=body).status_code == 422
    body["items"][0]["resolution"] = "one"
    body["items"][0]["quantity"] = "20"
    assert client.post(route, json=body).status_code == 422
    body["items"][0]["resolution"] = "sum"
    bad = {**body, "items": [*body["items"], {**body["items"][0], "group_id": "a" * 24}]}
    assert client.post(route, json=bad).status_code == 404
    unchanged = client.get("/api/documents/" + job.id).json()
    assert unchanged["updated_at"] == loaded["updated_at"]
    assert not unchanged["payload"]["groups"][0]["confirmed"]
    assert client.post(route, json={**body, "items": body["items"] * 2}).status_code == 422
    result = client.post(route, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["payload"]["summary"]["amount"] == 40
    assert result.json()["status"] == "ready"


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
