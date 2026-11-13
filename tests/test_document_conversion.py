import json

from test_workspaces import client as client
from test_workspaces import grant

from backend.documents import conversion, repository, retrieval, worker
from backend.documents.docling_runner import ENGINE, native_lines


def test_source_coordinates_and_cached_conversion_are_not_recomputed(tmp_path, monkeypatch):
    converted = native_lines(
        {
            "pages": {"2": {"size": {"width": 100, "height": 200}}},
            "texts": [
                {
                    "text": "Труба 12 м",
                    "prov": [
                        {
                            "page_no": 2,
                            "bbox": {
                                "l": 5,
                                "r": 80,
                                "t": 180,
                                "b": 170,
                                "coord_origin": "BOTTOMLEFT",
                            },
                        }
                    ],
                }
            ],
        },
        2,
    )
    assert converted["layout"]["lines"][0]["top"] == 20
    executable = tmp_path / "python"
    executable.touch()
    monkeypatch.setenv("DOCUMENT_DOCLING_PYTHON", str(executable))
    steps = []

    def run(command, **kwargs):
        target = tmp_path / "docling"
        target.mkdir()
        (target / "progress.json").write_text(json.dumps({"done": 1, "total": 2, "page": 1}))
        kwargs["on_tick"]()
        (target / "page-2.json").write_text(
            json.dumps({**converted, "source": "abc", "engine": ENGINE})
        )
        (target / "complete.json").write_text(
            json.dumps({"source": "abc", "engine": ENGINE, "pages": 2})
        )

    monkeypatch.setattr(conversion, "run", run)
    conversion.convert_document(tmp_path, "abc", 2, steps.append)
    assert steps[-1]["done"] == 1
    assert conversion.converted_page(tmp_path, 2, "abc")["text"].strip() == "Труба 12 м"
    assert conversion.converted_page(tmp_path, 2, "changed") is None
    monkeypatch.setattr(
        conversion, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Cache ignored"))
    )
    conversion.convert_document(tmp_path, "abc", 2, steps.append)
    assert steps[-1]["done"] == 2


def test_search_is_owner_scoped_and_text_download_revoked_after_deletion(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    grant(client, "9101")
    job = repository.create("local-admin", "Вентиляция.pdf")
    job.status = "needs_review"
    job.payload = {"file_hash": "abc", "text_complete": True}
    with repository.session() as database:
        database.add(job)
    folder = repository.folder(job.id) / "docling"
    folder.mkdir(parents=True)
    (folder / "document.md").write_text("Воздуховоды — 12 м", encoding="utf-8")
    (folder / "page-3.json").write_text(
        json.dumps(
            {"source": "abc", "text": "Объект\nВоздуховоды стальные — 12 м\nОборудование — 4 шт."}
        ),
        encoding="utf-8",
    )
    response = client.get(f"/api/documents/{job.id}/search?q=воздуховод")
    assert response.status_code == 200 and response.json()["results"][0]["page"] == 3
    assert "12 м" in response.json()["results"][0]["text"]
    assert (
        client.get(
            f"/api/documents/{job.id}/search?q=воздуховод", headers={"X-Preview-User": "9101"}
        ).status_code
        == 404
    )
    ticket = client.get(f"/api/documents/{job.id}/text.md?prepare=true").json()
    assert client.get(ticket["url"]).text == "Воздуховоды — 12 м"
    assert client.post(f"/api/documents/{job.id}/delete", json={}).status_code == 200
    assert client.get(ticket["url"]).status_code == 404


def test_bm25_prioritises_matching_structure_without_inventing_numbers():
    rows = [
        {"text": "Воздуховоды стальные — 12 м", "page": 5},
        {"text": "Отопление: 80 шт.", "page": 2},
    ]
    assert retrieval.rank("воздуховоды", rows)[0]["text"] == rows[0]["text"]
    assert retrieval.rank("несуществующая работа", rows) == []
    examples = [
        {"name": "Воздуховоды", "section": "Раздел этого файла", "unit": "м"},
        {"name": "Труба отопления", "section": "Другой раздел", "unit": "м"},
    ]
    assert retrieval.relevant_examples("Воздуховод", examples) == examples[:1]


def test_docling_streams_first_specification_to_ai_before_whole_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = repository.create("local-admin", "stream.pdf")
    job.pages = 3
    job.status = "extracting"
    payload = {
        "engine": "docling",
        "selection_policy": "specifications",
        "automatic": True,
        "file_hash": "abc",
    }
    job.payload = payload
    with repository.session() as database:
        database.add(job)
    path = repository.folder(job.id)
    path.mkdir(parents=True)
    (path / "source.pdf").touch()

    def convert(path, signature, pages, report, batch_size):
        assert batch_size == 1
        target = path / "docling"
        target.mkdir()
        value = {
            "source": "abc",
            "engine": ENGINE,
            "text": "Наименование Количество Единица измерения Труба 12 м",
            "layout": {"width": 100, "height": 200, "lines": []},
            "confidence": 85,
        }
        (target / "page-3.json").write_text(json.dumps(value), encoding="utf-8")
        report({"done": 1, "total": 3, "page": 3})
        return False

    monkeypatch.setattr(worker, "convert_document", convert)
    worker.process_docling(job.id, payload, path, 3)
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        assert saved.status == "ai_queued" and saved.processed == 1
        assert saved.payload["selected_specifications"] == [3]
        assert saved.payload["selection_streaming"] and not saved.payload["text_complete"]
        streaming_payload = saved.payload
    monkeypatch.setattr(worker.matcher, "provider", lambda *a: {"key": "test"})
    monkeypatch.setattr(
        worker,
        "extract_part",
        lambda *a, **kw: (
            [
                {
                    "name": "Монтаж трубы",
                    "category": "Вентиляция",
                    "section": "Раздел файла",
                    "quantity": 12,
                    "unit": "м",
                    "page": 3,
                    "quote": "Труба 12 м",
                }
            ],
            [],
        ),
    )
    worker.analyse(job.id, streaming_payload)
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        assert saved.status == "queued" and len(saved.payload["groups"]) == 1
        assert not saved.payload["coverage"]["complete"]
