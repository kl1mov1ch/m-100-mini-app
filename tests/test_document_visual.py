import asyncio
import json

import httpx
from PIL import Image

from backend import matcher
from backend.documents import visual
from backend.documents.normalization import build_groups


def test_multimodal_transport_keeps_images_and_uses_a_content_cache(monkeypatch):
    original = httpx.AsyncClient
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    def client(**kwargs):
        kwargs.pop("proxy", None)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(matcher.httpx, "AsyncClient", client)
    monkeypatch.setattr(matcher, "CACHE", {})
    settings = {
        "llm_api_key": "test",
        "llm_base_url": "https://example.test/v1",
        "llm_model": "vision-test",
    }
    content = [
        {"type": "text", "text": "read cells"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
    ]

    async def calls():
        assert await matcher.complete("JSON", content, settings) == {"ok": True}
        assert await matcher.complete("JSON", content, settings) == {"ok": True}

    asyncio.run(calls())
    assert len(bodies) == 1 and bodies[0]["messages"][1]["content"] == content


def fixture(tmp_path):
    directory = tmp_path / "docling"
    directory.mkdir()
    text = (
        "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество |\n"
        "Строка 2: C1–C2=Вентиляция |\n"
        "Строка 3: C1–C2=Диффузор универсальный | C2–C3=шт. | C3–C4=1 [OCR расходится: 11; проверить] |\n"
    )
    record = {
        "source": "abc",
        "method": "docling+tesseract",
        "text": text,
        "analysis_text": text,
        "layout": {"width": 100, "height": 100, "lines": []},
    }
    (directory / "page-1.json").write_text(json.dumps(record), encoding="utf-8")
    work = {
        "name": "Диффузор универсальный",
        "category": "Вентиляция",
        "page": 1,
        "source_row": 3,
        "unit_cell": "шт.",
        "quantity_cell": "1 [OCR расходится: 11; проверить]",
        "quantity_column": "C3–C4",
        "quantity_warning": True,
        "quote": "Исходная строка сохранена",
    }
    return {"file_hash": "abc", "works": [work]}


def test_visual_resolution_requires_independent_agreement_and_resumes_from_cache(
    tmp_path, monkeypatch
):
    payload = fixture(tmp_path)
    monkeypatch.setattr(visual, "evidence", lambda *a: {"QTY": Image.new("L", (100, 70), "white")})
    calls = []
    progress = []

    async def complete(system, content, settings):
        calls.append(content)
        return {
            "rows": [
                {
                    "id": "P1-R3",
                    "name": "Диффузор универсальный",
                    "unit": "шт.",
                    "quantity": "11",
                    "readable": True,
                }
            ]
        }

    def report(done, total, works):
        progress.append((done, total))

    result = asyncio.run(visual.resolve(tmp_path, payload, {}, complete, report))
    assert len(calls) == 2 and progress[-1] == (1, 1)
    assert (
        result[0]["visual_verified"]
        and result[0]["ocr_quantity"] == payload["works"][0]["quantity_cell"]
    )
    assert result[0]["quote"] == payload["works"][0]["quote"]
    assert build_groups(result)[0]["quantity"] == "11"
    asyncio.run(visual.resolve(tmp_path, payload, {}, complete, report))
    assert len(calls) == 2


def test_conflicting_visual_readings_do_not_become_a_payable_quantity(tmp_path, monkeypatch):
    payload = fixture(tmp_path)
    monkeypatch.setattr(visual, "evidence", lambda *a: {"QTY": Image.new("L", (100, 70), "white")})
    replies = iter(["11", "1"])

    async def complete(*args):
        return {
            "rows": [
                {
                    "id": "P1-R3",
                    "name": "Диффузор универсальный",
                    "unit": "шт.",
                    "quantity": next(replies),
                    "readable": True,
                }
            ]
        }

    result = asyncio.run(visual.resolve(tmp_path, payload, {}, complete, lambda *args: None))
    row = build_groups(result)[0]
    assert row["quantity"] is None and row["issues"]


def test_calibrated_ocr_reads_counts_locally_and_preserves_decimal_uncertainty(tmp_path):
    payload = fixture(tmp_path)
    path = tmp_path / "docling/page-1.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["digit_calibration"] = "header-glyphs-v1"
    record["verified_numeric_cells"] = [{"row": 3, "column": "C3–C4"}]
    path.write_text(json.dumps(record), encoding="utf-8")
    work = payload["works"][0]
    work.update(quantity_warning=False, quantity_cell="11", unit_present=True)

    async def unexpected(*args):
        raise AssertionError("Clear calibrated count must not be sent to vision")

    result = asyncio.run(visual.resolve(tmp_path, payload, {}, unexpected, lambda *args: None))
    assert result[0]["local_verified"] and build_groups(result)[0]["quantity"] == "11"
    assert not visual.local_reading(dict(work, unit_cell="м"), record)
    assert visual.local_reading(dict(work, unit_cell="м", quantity_cell="1,1"), record)
    assert not visual.local_reading(dict(work, source_row=4), record)
    assert not visual.local_reading(dict(work, quantity_column="C2–C3"), record)


def test_pdf_marks_continued_names_only_on_selected_pages(tmp_path):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    from backend.documents.annotations import annotated_pdf

    source = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=600, height=800)
    writer.write(source)
    box = {"left": 10, "top": 10, "width": 20, "height": 2}
    evidence = {
        "page": 3,
        "highlights": [box],
        "highlight_pages": [
            {"page": 1, "highlights": [box]},
            {"page": 2, "highlights": [box]},
        ],
    }
    marked = annotated_pdf(source, [{"sources": [evidence, evidence]}], {2, 3})
    pages = PdfReader(BytesIO(marked)).pages
    assert [len(page.get("/Annots", [])) for page in pages] == [0, 1, 1]


def test_recover_numeric_ocr_overwriting_a_name_without_moving_cell_boxes():
    from backend.documents.russian_cells import restore_names

    header = "Строка 1: C1–C2=Наименование |\n"
    name = "C1–C2=110 [OCR расходится: 110; проверить] | "
    quantity = "C2–C3=7 | "
    start = len(header + "Строка 2: ")
    record = {
        "analysis_text": header + "Строка 2: " + name + quantity,
        "analysis_layout": {
            "lines": [
                {"start": start, "end": start + len(name), "top": 20},
                {"start": start + len(name), "end": start + len(name + quantity), "top": 20},
            ]
        },
        "text_corrections": [
            {"column": "C1–C2", "top": 20, "before": "1. Вентилятор радиальный до №10"}
        ],
    }
    result = restore_names(record)
    first, second = result["analysis_layout"]["lines"]
    assert "Вентилятор радиальный" in result["analysis_text"][first["start"] : first["end"]]
    assert result["analysis_text"][second["start"] : second["end"]] == quantity
    assert first["top"] == second["top"] == 20


def test_duplicate_or_out_of_batch_ids_and_nonliteral_numbers_are_rejected():
    rows = visual.response_rows(
        {
            "rows": [
                {"id": "a", "quantity": "11"},
                {"id": "a", "quantity": "1"},
                {"id": "other", "quantity": "12"},
                {"id": "b", "quantity": "3+4"},
            ]
        },
        {"a", "b"},
    )
    assert "a" not in rows and "other" not in rows and rows["b"]["quantity"] is None
    assert visual.literal("1 200,25") == "1200,25"
    assert visual.literal("1 2") is None
    assert visual.literal("12\n34") is None
    assert visual.literal("12 / 1 200,25") == "12/1200,25"


def test_unit_change_triggers_second_read_and_compares_conversion_factors(tmp_path, monkeypatch):
    payload = fixture(tmp_path)
    path = tmp_path / "docling/page-1.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["verified_numeric_cells"] = [{"row": 3, "column": "C3–C4"}]
    path.write_text(json.dumps(record), encoding="utf-8")
    work = payload["works"][0]
    work.update(
        name="Прокладка трубы",
        category="Отопление",
        quantity_cell="12",
        unit_cell="м",
        unit_present=True,
        quantity_warning=False,
    )
    monkeypatch.setattr(visual, "evidence", lambda *a: {"QTY": Image.new("L", (100, 70), "white")})
    replies = iter(("см", "м"))

    async def complete(*args):
        return {
            "rows": [{"id": "P1-R3", "quantity": "12", "unit": next(replies), "readable": True}]
        }

    result = asyncio.run(visual.resolve(tmp_path, payload, {}, complete, lambda *a: None))
    assert result[0]["quantity_warning"] and not result[0].get("visual_verified")
    assert build_groups(result)[0]["quantity"] is None


def test_visual_crops_follow_the_source_columns(tmp_path, monkeypatch):
    data = [
        {"row": 1, "column": "C1–C2", "value": "Наименование"},
        {"row": 3, "column": "C2–C3", "value": "Труба"},
        {"row": 3, "column": "C5–C6", "value": "12"},
    ]
    context = {"name_column": "C2–C3", "surface_column": "C5–C6"}
    monkeypatch.setattr(visual, "cell_crop", lambda path, page, record, field, images: field)
    panels = visual.evidence(
        tmp_path,
        {"page": 1, "source_row": 3, "quantity_basis": "surface_schedule"},
        {1: {}},
        {(1, 3): context},
        {1: data},
    )
    assert panels == {"NAME": data[1], "QTY": data[2], "UNIT": None}


def test_progress_response_omits_intermediate_evidence_without_changing_the_job():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from backend.documents.repository import public

    payload = {
        "engine": "docling",
        "works": [{"name": "raw"}],
        "groups": [{"name": "draft"}],
        "analysis_done": 8,
        "analysis_total": 448,
    }
    job = SimpleNamespace(
        id="a" * 32,
        name="test.pdf",
        status="analysing",
        pages=83,
        processed=83,
        payload=payload,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    response = public(job, progress_only=True)
    assert "works" not in response["payload"] and "groups" not in response["payload"]
    assert response["payload"]["analysis_done"] == 8 and job.payload == payload
    job.status = "needs_review"
    assert public(job, progress_only=True)["payload"]["groups"] == payload["groups"]


def test_physical_continuation_retains_parent_work_without_retyping_quantity():
    work = {
        "name": "Решетка с горизонтальным расположением нерегулируемых жалюзи",
        "continuation_of": "Решетка с горизонтальным расположением нерегулируемых жалюзи",
        "category": "Вентиляция",
        "page": 1,
        "source_row": 8,
        "unit_cell": "шт.",
        "quantity_cell": "6",
    }
    result = visual.apply_reading(
        work,
        {"name": "Жалюзи алюминиевая", "unit": "шт.", "quantity": "6", "readable": True},
        "abc",
    )
    assert result["work_name"] == "Установка решеток (регулируемая)"
    assert build_groups([result])[0]["quantity"] == "6"


def test_revision_border_without_digit_is_not_a_quantity():
    from PIL import ImageDraw

    canvas = Image.new("L", (220, 90), "white")
    draw = ImageDraw.Draw(canvas)
    draw.arc((40, 55, 190, 125), 180, 360, fill=0, width=3)
    assert visual.annotation_only(canvas)
    draw.rectangle((80, 38, 99, 50), fill=0)
    assert not visual.annotation_only(canvas)
    assert not visual.annotation_only(Image.new("L", (220, 90), "white"))


def test_multiline_name_uses_only_matching_cells_and_does_not_count_notes(tmp_path):
    from backend.documents.structured import candidates

    directory = tmp_path / "docling"
    directory.mkdir()
    text = (
        "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество | C4–C5=Примечания |\n"
        "Строка 2: C1–C2=Вентиляция |\n"
        "Строка 3: C1–C2=1. Клапан противопожарный | C2–C3=шт. | C3–C4=2 | C4–C5=см. лист 70 |\n"
        "Строка 4: C1–C2=с электромеханическим приводом КПС-1М (24/220В) |\n"
        "Строка 5: C1–C2=с возвратной пружиной и клеммной колодкой |\n"
        "Строка 6: C1–C2=(см. лист 23) | C3–C4=23 |\n"
        "Строка 7: C1–C2=Ø200 | C3–C4=1 |\n"
        "Строка 8: C1–C2=2. Вентилятор радиальный | C2–C3=шт. | C3–C4=4 |\n"
        "Строка 9: C3–C4=(см. лист 25) |\n"
    )
    (directory / "page-1.json").write_text(
        json.dumps(
            {
                "source": "abc",
                "text": text,
                "analysis_text": text,
                "layout": {"width": 100, "height": 100, "lines": []},
            }
        ),
        encoding="utf-8",
    )
    works, _ = candidates(tmp_path, {"file_hash": "abc", "query": "вентиляция"})
    assert [w["source_row"] for w in works] == [3, 7, 8]
    assert tuple(works[0]["name_locations"]) == ((1, 3), (1, 4), (1, 5))
    assert "возвратной пружиной" in works[0]["source_description"]
    assert "см. лист" not in works[0]["quote"]
    assert works[0]["work_name"] == works[1]["work_name"]
    groups = build_groups(works)
    assert sorted(r["quantity"] for r in groups) == ["3", "4"]
