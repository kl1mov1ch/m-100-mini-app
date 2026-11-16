import asyncio
import io
import json

from pypdf import PdfReader, PdfWriter
from test_workspaces import client as client

from backend.documents import annotations, examples, extraction, repository, selection, worker
from backend.documents.normalization import build_groups
from backend.documents.structured import candidates


def test_structural_selection_does_not_reuse_fixed_section_names():
    assert (
        selection.classify_page(
            "Общие данные. Ведомость чертежей. Спецификация оборудования лист 72"
        )
        == "drawing"
    )
    assert selection.classify_page("План систем на отметке +3.000. Схема вентиляции") == "drawing"
    assert (
        selection.classify_page("Схема П1. Подбор по спецификации оборудования на листе 20")
        == "drawing"
    )
    assert selection.classify_page("Продолжение спецификации оборудования") == "specification"
    assert (
        selection.classify_page("Наименование Кол. Обозначение документа Поверхность м²")
        == "specification"
    )
    assert (
        selection.classify_page(
            "Наименование Количество Единица измерения Неизвестный пользовательский раздел"
        )
        == "specification"
    )
    assert selection.classify_page("Теплоизоляционные материалы") == "uncertain"


def test_section_query_starts_inside_a_mixed_sheet_and_continues_on_the_next(tmp_path):
    header = "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество |"
    texts = [
        header + "\n"
        "Строка 2: C1–C2=Отопление |\n"
        "Строка 3: C1–C2=Радиатор | C2–C3=шт. | C3–C4=50 |\n"
        "Строка 4: C1–C2=Вентиляция |\n"
        "Строка 5: C1–C2=Вентилятор | C2–C3=шт. | C3–C4=7 |\n",
        header + "\n"
        "Строка 2: C1–C2=Изделия и материалы |\n"
        "Строка 3: C1–C2=Решётка | C2–C3=шт. | C3–C4=16 |\n"
        "Строка 4: C1–C2=Отопление |\n"
        "Строка 5: C1–C2=Труба | C2–C3=м | C3–C4=90 |",
    ]
    records = tmp_path / "docling"
    records.mkdir()
    for number, content in enumerate(texts, 1):
        (records / f"page-{number}.json").write_text(
            json.dumps({"source": "test", "text": content, "analysis_text": content}),
            encoding="utf-8",
        )
    works, controls = candidates(
        tmp_path, {"file_hash": "test", "query": "Вентиляция кроме пусконаладки"}
    )
    assert [(row["page"], row["source_row"], row["quantity_cell"]) for row in works] == [
        (1, 5, "7"),
        (2, 3, "16"),
    ]
    assert {row["category"] for row in works} == {"Вентиляция"}
    assert not controls


def test_categories_stay_separate_and_copies_only_count_once():
    work = {
        "name": "Монтаж материала",
        "category": "Прочее",
        "section": "Раздел заказчика",
        "subsection": "Блок А",
        "item_code": "A-12",
        "page_digest": "identical-source-page",
        "quantity": 5,
        "unit": "м",
        "page": 2,
        "quote": "A-12 Материал 5 м",
    }
    groups = build_groups([work, {**work, "page": 9}])
    assert groups[0]["quantity"] == "5" and not groups[0]["issues"]
    assert len(groups[0]["sources"]) == 1 and len(groups[0]["duplicate_sources"]) == 1
    independent = build_groups([work, {**work, "page": 9, "page_digest": "another-source-page"}])[0]
    assert (
        independent["quantity"] is None
        and independent["proposed_quantity"] == "10"
        and independent["issues"]
    )
    combined = build_groups(
        [
            work,
            {
                **work,
                "section": "Другой раздел",
                "category": "Вентиляция",
                "source_row": 2,
                "quote": "П2: материал 6 м",
                "quantity": 6,
            },
        ]
    )
    assert {row["category"]: row["quantity"] for row in combined} == {
        "Прочее": "5",
        "Вентиляция": "6",
    }
    assert all(row["mention_count"] == 1 for row in combined)
    ambiguous = build_groups([{**work, "item_code": ""}, {**work, "item_code": "", "page": 9}])[0]
    assert ambiguous["quantity"] is None and ambiguous["issues"]


def test_confirmed_examples_start_empty_and_are_owner_scoped(client):
    assert examples.confirmed_examples("local-admin") == []
    job = repository.create("local-admin", "learn.pdf")
    job.payload = {
        "groups": [
            {
                "name": "Материал",
                "section": "Личный раздел",
                "subsection": "Узел",
                "unit": "м",
                "confirmed": False,
                "quantity": "999",
                "rate": "500",
            }
        ]
    }
    with repository.session() as database:
        database.add(job)
    assert examples.confirmed_examples("local-admin") == []
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        saved.payload = {"groups": [{**saved.payload["groups"][0], "confirmed": True}]}
        examples.remember(database, "local-admin", saved.payload["groups"])
        examples.remember(database, "local-admin", saved.payload["groups"])
        database.delete(saved)
    learned = examples.confirmed_examples("local-admin")
    assert len(learned) == 1 and "quantity" not in learned[0] and "rate" not in learned[0]
    assert examples.confirmed_examples("another-owner") == []
    with repository.session() as database:
        from sqlalchemy import select

        assert database.scalar(select(repository.RecognitionExample.confirmations)) == 2


def test_rebuild_keeps_only_confirmed_structure_and_respects_version_and_owner(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = repository.create("local-admin", "learn.pdf")
    job.status = "needs_review"
    job.payload = {
        "file_hash": "sample",
        "query": "Вентиляция",
        "groups": [
            {
                "name": "Монтаж",
                "section": "Раздел файла",
                "subsection": "Узел",
                "unit": "м",
                "confirmed": True,
                "quantity": "70",
                "rate": "25",
            },
            {"name": "Не подтверждено", "section": "Шум", "confirmed": False},
        ],
    }
    with repository.session() as database:
        database.add(job)
    endpoint = f"/api/documents/{job.id}/rebuild"
    assert client.post(endpoint, json={"version": "old"}).status_code == 409
    response = client.post(endpoint, json={"version": repository.version(job.updated_at)})
    assert response.status_code == 200, response.text
    payload = response.json()["payload"]
    assert response.json()["status"] == "queued" and len(payload["groups"]) == 1
    assert payload["groups"][0]["quantity"] == "70" and payload["groups"][0]["rate"] == "25"
    assert payload["selection_policy"] == "specifications"
    assert len(payload["learned_examples"]) == 1
    assert not {"quantity", "rate"} & payload["learned_examples"][0].keys()
    assert examples.confirmed_examples("local-admin")[0]["section"] == "Раздел файла"
    assert client.post(endpoint, json={"version": response.json()["updated_at"]}).status_code == 409
    from test_workspaces import grant

    grant(client, "8101")
    assert (
        client.post(
            endpoint,
            headers={"X-Preview-User": "8101"},
            json={"version": response.json()["updated_at"]},
        ).status_code
        == 404
    )
    with repository.session() as database:
        database.get(repository.DocumentJob, job.id).status = "published"
    assert client.post(endpoint, json={"version": response.json()["updated_at"]}).status_code == 409


def test_model_sections_must_be_from_this_file_not_confirmed_examples():
    async def complete(*args):
        return {
            "works": [
                {
                    "name": "Монтаж трубы",
                    "category": "Вентиляция",
                    "unit": "м",
                    "quantity": 12,
                    "quote": "Труба 12 м",
                    "section": "Чужой раздел",
                    "subsection": "Система этого файла",
                    "item_code": "чужая позиция",
                }
            ]
        }

    works, _ = asyncio.run(
        extraction.propose(
            "Система этого файла. Труба 12 м",
            1,
            {"document_examples": [{"section": "Чужой раздел"}]},
            complete=complete,
        )
    )
    assert works[0]["section"] == "Без раздела"
    assert works[0]["subsection"] == "Система этого файла" and not works[0]["item_code"]


def test_strict_pipeline_never_ocr_or_analyse_drawing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=300, height=300)
    content = io.BytesIO()
    writer.write(content)
    reserved = client.post(
        "/api/documents/reserve", json={"name": "project.pdf", "selection_policy": "specifications"}
    ).json()
    ident = reserved["id"]
    client.post(f"/api/documents/{ident}/file", files={"file": ("project.pdf", content.getvalue())})
    monkeypatch.setattr(
        worker,
        "page_index",
        lambda *args: [
            {"page": 1, "kind": "drawing"},
            {"page": 2, "kind": "specification"},
            {"page": 3, "kind": "uncertain"},
        ],
    )
    seen = []

    def ocr(source, page, path):
        seen.append(page)
        return "Наименование Количество Единица измерения Материал 5 м"

    monkeypatch.setattr(worker, "ocr_page", ocr)
    assert worker.run_once()
    assert seen == [2]
    with repository.session() as database:
        job = database.get(repository.DocumentJob, ident)
        assert job.payload["selected_specifications"] == [2]
        assert job.payload["page_results"][0]["kind"] == "excluded_drawing"
        assert job.payload["questions"]
    source = repository.folder(ident) / "source.pdf"
    groups = [
        {
            "sources": [
                {"page": p, "highlights": [{"left": 1, "top": 1, "width": 20, "height": 1}]}
                for p in [1, 2, 3]
            ]
        }
    ]
    result = annotations.annotated_pdf(source, groups, {2})
    pages = PdfReader(io.BytesIO(result)).pages
    assert not pages[0].get("/Annots") and pages[1].get("/Annots") and not pages[2].get("/Annots")
