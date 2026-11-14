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
