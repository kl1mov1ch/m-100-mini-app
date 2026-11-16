import asyncio
import io
import json

import openpyxl
from sqlalchemy import select
from test_workspaces import client as client_fixture  # noqa: F401
from test_workspaces import grant

from backend.documents import repository, worker
from backend.documents.normalization import build_groups
from backend.documents.work_rates import suggest_rates


def test_manual_rate_is_shared_across_document_owners(client_fixture, monkeypatch, tmp_path):  # noqa: F811
    client = client_fixture
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    grant(client, "1001")
    grant(client, "1002")

    def make_job(owner, name, status):
        work = {
            "name": name,
            "work_name": name,
            "category": "Отопление",
            "unit": "шт.",
            "quantity": 4,
            "page": 1,
            "quote": name,
        }
        job = repository.create(owner, "estimate.pdf")
        job.status = status
        job.payload = {
            "groups": build_groups([work]) if status == "needs_review" else [],
            "works": [work],
            "structured_extraction": True,
            "visual_complete": True,
            "selection_complete": True,
            "selected_specifications": [1],
        }
        with repository.session() as database:
            database.add(job)
        return job

    def confirm(job, rate):
        headers = {"X-Preview-User": job.owner_id}
        url = "/api/documents/" + job.id
        data = client.get(url, headers=headers).json()
        row = data["payload"]["groups"][0]
        return client.post(
            url + "/groups/" + row["id"],
            headers=headers,
            json={
                "version": data["updated_at"],
                "quantity": "4",
                "rate": rate,
                "unit": "шт.",
            },
        )

    reference = make_job("1001", "Монтаж стального радиатора", "needs_review")
    assert confirm(reference, "42.125").status_code == 200

    async def compare(prompt, text, settings):
        assert "42.125" not in text
        assert "Монтаж стального радиатора" in text
        assert len(json.loads(text)["items"]) == 1
        return {"matches": [{"index": 0, "candidate": 0, "rate": 999}]}

    monkeypatch.setattr(worker.matcher, "provider", lambda settings: {"key": "test"})
    monkeypatch.setattr(worker.matcher, "complete", compare)
    other = make_job("1002", "Установка стального радиатора", "ai_queued")
    worker.analyse(other.id, other.payload)
    with repository.session() as database:
        row = database.get(repository.DocumentJob, other.id).payload["groups"][0]
        assert row["rate"] == "42.125"
        assert row["rate_suggestion"] == {"name": "Монтаж стального радиатора", "method": "ai"}
        assert not row["confirmed"]

    draft = client.get(f"/api/documents/{other.id}/export.xlsx", headers={"X-Preview-User": "1002"})
    assert draft.status_code == 200, draft.text
    with io.BytesIO(draft.content) as stream:
        book = openpyxl.load_workbook(stream)
        assert book.active["E5"].value == 42.125
        assert "Монтаж стального радиатора" in book.active["E5"].comment.text
        book.close()

    assert confirm(other, "42.125").status_code == 200
    with repository.session() as database:
        assert len(list(database.scalars(select(repository.WorkRate)))) == 1
    assert confirm(other, "48").status_code == 200
    assert confirm(other, "51").status_code == 200

    probe = {"category": "Отопление", "unit": "шт.", "rate": None}
    candidates = [
        {**probe, "name": "УСТАНОВКА СТАЛЬНОГО РАДИАТОРА"},
        {**probe, "name": "Монтаж стального радиатора"},
        {**probe, "name": "Монтаж стального радиатора", "unit": "компл."},
        {**probe, "name": "Монтаж стального радиатора 500"},
        {**probe, "name": "Демонтаж стального радиатора"},
        {**probe, "name": "Монтаж стального радиатора", "subsection": "Пусконаладочные работы"},
        {**probe, "name": "Монтаж стального радиатора", "confirmed": True, "rate": "14"},
    ]
    expected_rates = ["51", "42.125", None, None, None, None, "14"]

    async def unexpected(*args):
        raise AssertionError("Only incompatible or exact matches remain")

    asyncio.run(suggest_rates(candidates, {}, unexpected))
    assert [row["rate"] for row in candidates] == expected_rates
