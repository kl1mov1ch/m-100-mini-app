import io
import json

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine
from test_document_jobs import sample_pdf
from test_workspaces import client as client

from backend.documents import page_cache, progress, repository, worker


def test_postgres_session_persists_changes_without_manual_flush(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "postgres-session.db"),
        execution_options={"schema_translate_map": {"registry": None}},
    )
    repository.DocumentJob.__table__.create(engine)
    monkeypatch.setattr(repository.postgres, "enabled", lambda: True)
    monkeypatch.setattr(repository.postgres, "pool", lambda: engine)
    job = repository.create("local-admin", "progress.pdf")
    with repository.session() as database:
        database.add(job)
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        assert saved is not None
        saved.status = "extracting"
        saved.processed = 3
        saved.payload = {"progress": {"stage": "ocr", "page": 4}}
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        assert (saved.status, saved.processed, saved.payload["progress"]["page"]) == (
            "extracting",
            3,
            4,
        )
    with pytest.raises(ValueError), repository.session() as database:
        database.get(repository.DocumentJob, job.id).processed = 99
        raise ValueError("rollback")
    with repository.session() as database:
        assert database.get(repository.DocumentJob, job.id).processed == 3
        database.delete(database.get(repository.DocumentJob, job.id))
    with repository.session() as database:
        assert database.get(repository.DocumentJob, job.id) is None
    engine.dispose()


def test_upload_returns_metadata_and_wakes_worker_after_commit(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = client.post("/api/documents/reserve", json={"name": "project.pdf"}).json()
    result = client.post(
        f"/api/documents/{job['id']}/file", files={"file": ("project.pdf", sample_pdf())}
    )
    assert result.status_code == 200, result.text
    assert result.json()["pages"] == 1
    assert result.json()["payload"]["file_bytes"] == len(sample_pdf())
    assert (tmp_path / "data/document-queue.signal").exists()
    assert client.get(f"/api/documents/{job['id']}").json()["status"] == "queued"


def test_ocr_and_ai_publish_partial_results_before_document_finishes(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=300, height=300)
    output = io.BytesIO()
    writer.write(output)
    result = client.post("/api/documents", files={"file": ("project.pdf", output.getvalue())})
    ident = result.json()["id"]
    assert result.json()["pages"] == 3
    monkeypatch.setattr(
        worker,
        "ocr_page",
        lambda source, number, destination: f"Спецификация: труба П{number} — 10 м, монтаж.",
    )
    monkeypatch.setattr(worker.matcher, "provider", lambda _: {"key": "test"})

    async def complete(prompt, content, settings):
        page = json.loads(content)["page"]
        return {
            "works": [
                {
                    "name": f"Монтаж трубы П{page}",
                    "category": "Вентиляция",
                    "unit": "м",
                    "quantity": 10,
                    "quote": f"труба П{page} — 10 м",
                }
            ],
            "questions": [],
        }

    monkeypatch.setattr(worker.matcher, "complete", complete)
    assert worker.run_once()
    job = client.get(f"/api/documents/{ident}").json()
    assert (job["status"], job["processed"], job["pages"]) == ("ai_queued", 1, 3)
    assert worker.run_once()
    partial = client.get(f"/api/documents/{ident}").json()
    assert partial["status"] == "queued" and len(partial["payload"]["groups"]) == 1
    assert partial["payload"]["coverage"]["complete"] is False
    assert client.get(f"/api/documents/{ident}/export.xlsx?final=true").status_code == 409
    assert worker.run_once()
    assert worker.run_once()
    finished = client.get(f"/api/documents/{ident}").json()
    assert finished["status"] == "needs_review"
    assert finished["processed"] == 3 and len(finished["payload"]["groups"]) == 3
    assert finished["payload"]["coverage"]["complete"] is True
    assert finished["payload"]["analysis_done"] == finished["payload"]["analysis_total"] == 3
    brief = client.get("/api/documents").json()[0]
    assert brief["payload"]["progress"]["stage"] == "ai"
    assert brief["payload"]["analysis_done"] == 3


def test_cache_reuses_extraction_but_rejects_changed_or_truncated_text(tmp_path):
    (tmp_path / "source.pdf").write_bytes(sample_pdf())
    page_cache.cache_page(tmp_path, 1, "Труба — 12 м", 89, None, "source-hash")
    cached = page_cache.cached_page(tmp_path, 1, "source-hash")
    assert cached["text"] == "Труба — 12 м" and cached["confidence"] == 89
    assert page_cache.cached_page(tmp_path, 1, "another-file") is None
    (tmp_path / "page-1.txt").write_text("Труба", encoding="utf-8")
    assert page_cache.cached_page(tmp_path, 1, "source-hash") is None


def test_restart_recovers_interrupted_job_and_metadata(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = repository.create("local-admin", "progress.pdf")
    job.status = "analysing"
    path = repository.folder(job.id)
    path.mkdir(parents=True)
    (path / "source.pdf").write_bytes(sample_pdf())
    with repository.session() as database:
        database.add(job)
    progress.recover_interrupted()
    result = client.get(f"/api/documents/{job.id}").json()
    assert result["status"] == "ai_queued" and result["pages"] == 1
    stamp = result["updated_at"]
    assert progress.heartbeat(job.id)
    assert client.get(f"/api/documents/{job.id}").json()["updated_at"] > stamp
