import base64
import io
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import openpyxl
import httpx
import pytest
from pypdf import PdfReader
from test_document_jobs import sample_pdf
from test_workspaces import client

from backend import profile_webhooks
from backend.documents import execution, publication, repository, worker
from backend.documents.normalization import build_groups, financial_summary


def test_cancellation_terminates_active_ocr_process(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    ident = ready_job(tmp_path)
    children = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(execution.subprocess, "Popen", start)

    def cancel():
        time.sleep(0.2)
        with repository.session() as database:
            database.delete(database.get(repository.DocumentJob, ident))

    thread = threading.Thread(target=cancel)
    thread.start()
    token = execution.current_job.set(ident)
    before = time.monotonic()
    try:
        with pytest.raises(execution.JobDeleted):
            execution.run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                capture_output=True,
                timeout=35,
            )
    finally:
        execution.current_job.reset(token)
        thread.join()
    assert time.monotonic() - before < 5
    assert children[0].poll() is not None


def ready_job(tmp_path):
    job = repository.create("local-admin", "project.pdf")
    row = build_groups(
        [
            {
                "name": "Монтаж трубы",
                "category": "Отопление",
                "unit": "м",
                "quantity": 12,
                "page": 1,
                "quote": "Труба 12 м",
                "notes": "Высота 12 м",
                "highlights": [{"left": 10, "top": 20, "width": 30, "height": 2}],
            }
        ]
    )[0]
    row.update(confirmed=True, rate="2.5", amount=30)
    job.status = "ready"
    job.pages = job.processed = 1
    job.payload = {
        "groups": [row],
        "summary": financial_summary([row]),
        "coverage": {"complete": True},
        "query": "Отопление",
    }
    path = repository.folder(job.id)
    path.mkdir(parents=True)
    (path / "source.pdf").write_bytes(sample_pdf())
    with repository.session() as database:
        database.add(job)
        database.flush()
    return job.id


def test_reservation_cancel_and_delete_remove_file_and_metadata(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = client.post(
        "/api/documents/reserve", json={"name": "project.pdf", "query": "Вентиляция"}
    ).json()
    ident = job["id"]
    assert job["status"] == "uploading"
    assert client.post(f"/api/documents/{ident}/delete", json={}).status_code == 200
    assert not repository.folder(ident).exists()
    assert (
        client.post(
            f"/api/documents/{ident}/file", files={"file": ("project.pdf", sample_pdf())}
        ).status_code
        == 404
    )
    assert client.get(f"/api/documents/{ident}").status_code == 404
    assert not client.get("/api/documents").json()


def test_reserved_upload_and_cancel_during_analysis_cannot_restore_job(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = client.post("/api/documents/reserve", json={"name": "project.pdf"}).json()
    ident = job["id"]
    assert (
        client.post(
            f"/api/documents/{ident}/file", files={"file": ("project.pdf", sample_pdf())}
        ).json()["status"]
        == "queued"
    )

    def cancelled_ocr(*args):
        with repository.session() as database:
            database.delete(database.get(repository.DocumentJob, ident))
        execution.check_active()

    monkeypatch.setattr(worker, "ocr_page", cancelled_ocr)
    assert worker.run_once()
    assert client.get(f"/api/documents/{ident}").status_code == 404
    assert not repository.folder(ident).exists()


def test_annotated_pdf_preserves_every_page_and_revokes_download_after_delete(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    ident = ready_job(tmp_path)
    result = client.get(f"/api/documents/{ident}/marked.pdf")
    assert result.status_code == 200
    book = PdfReader(io.BytesIO(result.content))
    assert len(book.pages) == 1
    annotation = book.pages[0]["/Annots"][0].get_object()
    assert annotation["/Subtype"] == "/Highlight"
    assert list(annotation["/C"]) == pytest.approx([1, 225 / 255, 0])
    assert float(annotation["/CA"]) == pytest.approx(0.32)
    ticket = client.get(f"/api/documents/{ident}/marked.pdf?prepare=true").json()
    client.post(f"/api/documents/{ident}/delete", json={})
    assert client.get(ticket["url"]).status_code == 404


@pytest.mark.parametrize("mode", ["normal", "changed", "lost_response"])
def test_publish_requires_empty_unchanged_file_and_is_idempotent(
    client, monkeypatch, tmp_path, mode
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    ident = ready_job(tmp_path)
    hook = profile_webhooks.save_webhook(
        "local-admin", "Диск", "https://demo.bitrix24.by/rest/1/abc123/"
    )
    output = io.BytesIO()
    openpyxl.Workbook().save(output)
    remote = {"content": output.getvalue(), "writes": 0}

    async def resolve(*args):
        return 9

    async def download(*args):
        return remote["content"], {"NAME": "Пустой.xlsx", "ID": "9"}

    async def rest(webhook, method, payload):
        assert method == "disk.file.uploadVersion"
        remote["writes"] += 1
        remote["content"] = base64.b64decode(payload["fileContent"][1])
        if mode == "lost_response" and remote["writes"] == 1:
            raise httpx.ReadTimeout("Lost response after upload")
        return True

    monkeypatch.setattr(publication.bitrix, "resolve_public_file", resolve)
    monkeypatch.setattr(publication.bitrix, "download_rest", download)
    monkeypatch.setattr(publication.bitrix, "rest", rest)
    job = client.get(f"/api/documents/{ident}").json()
    body = {
        "version": job["updated_at"],
        "public_url": "https://bitrix24public.com/demo.bitrix24.by/sheet/abc123",
        "webhook_id": hook["id"],
        "object_name": "PDF объект",
    }
    preview = client.post(f"/api/documents/{ident}/bitrix/preview", json=body)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert "_publication_webhook" not in data["payload"]
    token = data["payload"]["publication"]["token"]
    if mode == "changed":
        changed = openpyxl.Workbook()
        changed.active["A1"] = "Ручные данные"
        modified = io.BytesIO()
        changed.save(modified)
        remote["content"] = modified.getvalue()
    result = client.post(
        f"/api/documents/{ident}/bitrix/publish",
        json={"version": data["updated_at"], "token": token},
    )
    if mode == "changed":
        assert result.status_code == 409 and remote["writes"] == 0
        assert (
            openpyxl.load_workbook(io.BytesIO(remote["content"])).active["A1"].value
            == "Ручные данные"
        )
        reset = client.post(f"/api/documents/{ident}/bitrix/reset", json={})
        assert reset.status_code == 200 and reset.json()["status"] == "ready"
        return
    if mode == "lost_response":
        assert result.status_code == 409 and remote["writes"] == 1
        retry = client.get(f"/api/documents/{ident}").json()
        result = client.post(
            f"/api/documents/{ident}/bitrix/publish",
            json={"version": retry["updated_at"], "token": token},
        )
    assert result.status_code == 200, result.text
    published = result.json()
    assert published["status"] == "published" and remote["writes"] == 1
    project_id = published["payload"]["publication"]["project_id"]
    parsed = client.get("/api/bootstrap", headers={"X-Project-Id": project_id}).json()
    assert parsed["positions"][0]["planned"] == 12
    assert parsed["positions"][0]["rate"] == 2.5
    repeat = client.post(
        f"/api/documents/{ident}/bitrix/publish",
        json={"version": published["updated_at"], "token": token},
    )
    assert repeat.status_code == 200 and remote["writes"] == 1
    assert client.get(f"/api/documents/{ident}/export.xlsx?final=true").status_code == 200
    with pytest.raises(ValueError):
        publication.ensure_empty(remote["content"])
