import json

from PIL import Image, ImageDraw, ImageFont
from test_workspaces import client as client

from backend.documents import repository, worker
from backend.documents.docling_runner import ENGINE
from backend.documents.glyph_numbers import calibrate
from backend.documents.intent import requested_categories
from backend.documents.normalization import build_groups, normalise
from backend.documents.profile import load_prompt, load_template, profile_version


def test_profile_is_external_and_does_not_supply_project_quantities_or_prices():
    template = load_template()
    assert len(template["works"]) == 24
    assert all("quantity" not in row and "rate" not in row for row in template["works"])
    assert "source_row" in load_prompt("extract")
    assert len(profile_version()) == 16
    assert requested_categories("ветиляцию подбей все") == {"Вентиляция"}
    assert requested_categories("отопление и вентиляция") == {"Отопление", "Вентиляция"}
    assert requested_categories("все направления") == set()


def test_composite_quantity_uses_area_and_keeps_original_cells():
    row = normalise(
        {
            "name": "Воздуховод 200х300",
            "category": "Вентиляция",
            "unit_cell": "м/м²",
            "quantity_cell": "10/6,28",
            "quantity": None,
        }
    )
    assert row["unit"] == "м²" and row["quantity"] == "6.28"
    assert row["original_unit"] == "м/м²" and row["original_quantity"] == "10/6,28"
    rows = build_groups(
        [
            {
                "name": "Клей термостойкий",
                "category": "Вентиляция",
                "unit": "кг",
                "quantity": 5,
                "page": 20,
                "source_row": 1,
            },
            {
                "name": "Лента алюминиевая",
                "category": "Вентиляция",
                "unit": "м",
                "quantity": 10,
                "page": 21,
                "source_row": 1,
            },
        ]
    )
    assert len(rows) == 1 and rows[0]["name"] == "Расходный материал"
    assert rows[0]["quantity"] == "1" and rows[0]["unit"] == "компл."
    assert rows[0]["source_summary"] == "стр. 20 — 1 упомин.; стр. 21 — 1 упомин."


def numeric_fixture(printed, read):
    image = Image.new("L", (1000, 310), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    text, lines = "", []

    def cell(row, column, value, top, bottom):
        nonlocal text
        start = len(text)
        text += f"C{column}–C{column + 1}={value} | "
        left = 20 + (column - 1) * 100
        lines.append(
            {
                "start": start,
                "end": len(text),
                "left": left,
                "top": top,
                "right": left + 95,
                "bottom": bottom,
            }
        )

    text += "Строка 1: "
    for column in range(1, 10):
        cell(
            1,
            column,
            {2: "Наименование", 6: "Единица измерения", 7: "Количество"}.get(column, "Заголовок"),
            10,
            80,
        )
    text += "\nСтрока 2: "
    for column in range(1, 10):
        cell(2, column, str(column), 100, 150)
        draw.text((20 + (column - 1) * 100 + 20, 110), str(column), fill=0, font=font)
    text += "\nСтрока 3: "
    cell(3, 7, read, 190, 250)
    draw.text((640, 200), printed, fill=0, font=font)
    return image, {
        "analysis_text": text,
        "analysis_layout": {"width": 1000, "height": 310, "lines": lines},
    }


def test_numeric_calibration_reads_font_instead_of_copying_a_reference_total():
    image, record = numeric_fixture("1", "7")
    corrected = calibrate(image, record)
    assert corrected["numeric_corrections"][0]["after"] == "1"
    assert "C7–C8=1 |" in corrected["analysis_text"]
    image, record = numeric_fixture("7", "7")
    assert not calibrate(image, record)["numeric_corrections"]
    image, record = numeric_fixture("2.64", "264 [OCR расходится: 2,64; проверить]")
    assert calibrate(image, record)["numeric_corrections"][0]["after"] == "2,64"


def test_structured_job_automatically_aggregates_without_ai_recounting(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(repository.store, "ROOT", tmp_path)
    job = repository.create("local-admin", "automatic.pdf")
    job.pages = 1
    job.status = "extracting"
    payload = {"engine": "docling", "automatic": True, "file_hash": "abc", "query": "ветиляцию"}
    job.payload = payload
    with repository.session() as database:
        database.add(job)
    path = repository.folder(job.id)
    path.mkdir(parents=True)
    (path / "source.pdf").touch()
    text = "Таблица: ячейки по строкам и колонкам.\n"
    text += "Строка 1: C1–C2=Наименование | C2–C3=Количество | C3–C4=Единица измерения |\n"
    text += "Строка 2: C1–C2=Вентиляция |\n"
    text += "Строка 3: C1–C2=Вентилятор радиальный №5 | C2–C3=7 | C3–C4=шт. |\n"
    text += "Строка 4: C1–C2=Вентилятор радиальный №10 | C2–C3=16 | C3–C4=шт. |\n"

    def convert(path, signature, pages, report, batch_size):
        directory = path / "docling"
        directory.mkdir()
        (directory / "page-1.json").write_text(
            json.dumps(
                {
                    "source": "abc",
                    "engine": ENGINE,
                    "text": "Спецификация",
                    "analysis_text": text,
                    "layout": {"width": 100, "height": 100, "lines": []},
                    "confidence": 95,
                }
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(worker, "convert_document", convert)
    worker.process_docling(job.id, payload, path, 1)
    monkeypatch.setattr(worker.matcher, "provider", lambda *_: {"key": "test"})

    async def unexpected(*args):
        raise AssertionError("Known table rows must not be retold or counted by AI")

    monkeypatch.setattr(worker.matcher, "complete", unexpected)
    with repository.session() as database:
        parsed = database.get(repository.DocumentJob, job.id).payload
    worker.analyse(job.id, parsed)
    with repository.session() as database:
        saved = database.get(repository.DocumentJob, job.id)
        assert saved.status == "needs_review" and saved.payload["coverage"]["complete"]
        assert len(saved.payload["groups"]) == 1
        row = saved.payload["groups"][0]
        assert row["name"] == "Монтаж вентиляторов (радиальных)" and row["quantity"] == "23"
        assert row["source_summary"] == "стр. 1 — 2 упомин."
        assert saved.payload.get("ai_calls", 0) == 0


def test_cells_outside_grid_do_not_discard_a_real_work_row():
    from backend.documents.parsed_tables import estimate_table
    from backend.documents.table_context import document_rows

    text = (
        "Строка 1: C2–C3=Наименование | C3–C4=Единица измерения | C4–C5=Количество |\n"
        "Строка 2: C2–C3=Вентиляция |\n"
        "Строка 3: C1–C2=Служебная отметка | C2–C3=Диффузор универсальный Ø125 | C3–C4=шт. | C4–C5=1 200,25 |\n"
        "Строка 4: C2–C3=Ø160 | C3–C4=шт. | C4–C5=2 |\n"
    )
    table = estimate_table({"analysis_text": text})
    assert table and "Служебная отметка" not in table["text"]
    assert "Ø125" in table["text"] and "1 200,25" in table["text"]
    context = document_rows({1: table})
    assert context[1, 3]["quantity_cell"] == "1 200,25"
    item = normalise(
        {
            "category": "Вентиляция",
            "name": context[1, 3]["name"],
            "unit_cell": context[1, 3]["unit_cell"],
            "quantity_cell": context[1, 3]["quantity_cell"],
        }
    )
    assert item["quantity"] == "1200.25"


def test_assembly_children_do_not_become_extra_paid_work():
    from backend.documents.parsed_tables import estimate_table
    from backend.documents.table_context import document_rows

    text = (
        "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество |\n"
        "Строка 2: C1–C2=Вентиляция |\n"
        "Строка 3: C1–C2=Оборудование |\n"
        "Строка 4: C1–C2=1 Приточная установка | C2–C3=компл. | C3–C4=1 |\n"
        "Строка 5: C1–C2=левой стороной обслуживания 6 составе: |\n"
        "Строка 6: C1–C2=6) Вентилятор радиальный | C2–C3=шт. | C3–C4=2 |\n"
        "Строка 7: C1–C2=В комплекте со щитом автоматики |\n"
        "Строка 8: C1–C2=Изделия и материалы |\n"
        "Строка 9: C1–C2=1 Диффузор универсальный | C2–C3=шт. | C3–C4=4 |\n"
    )
    table = estimate_table({"analysis_text": text})
    rows = document_rows({1: table})
    assert rows[1, 6]["component"] and rows[1, 6]["category"] == "Вентиляция"
    assert not rows[1, 9]["component"] and rows[1, 9]["name"] == "1 Диффузор универсальный"


def test_geometry_requires_dimensions_and_preserves_original_length():
    from decimal import Decimal

    from backend.documents.geometry import perimeter

    assert perimeter(None, "200×300") == Decimal("1")
    assert abs(perimeter(None, "Ø200") - Decimal("0.6283185307179586")) < Decimal("0.000000001")
    assert perimeter({"kind": "round", "diameter_mm": "NaN"}) is None
    row = normalise(
        {
            "name": "Воздуховод 200×300",
            "category": "Вентиляция",
            "unit_cell": "м",
            "quantity_cell": "12,5",
            "dimension_text": "200×300",
        }
    )
    assert (
        row["quantity"] == "12.5000" and row["unit"] == "м²" and row["original_quantity"] == "12,5"
    )
    row = normalise(
        {"name": "Воздуховод", "category": "Вентиляция", "unit_cell": "м", "quantity_cell": "12,5"}
    )
    assert row["quantity"] is None


def test_separate_table_rows_are_added_and_disagreements_are_never_zeroed():
    works = [
        {
            "name": "Диффузор универсальный",
            "category": "Вентиляция",
            "unit_cell": "шт.",
            "quantity_cell": "2",
            "page": page,
            "source_row": 5,
            "quote": "Одинаковая строка",
            "page_digest": str(page),
        }
        for page in [20, 21]
    ]
    row = build_groups(works)[0]
    assert row["quantity"] == "4" and not row["issues"]
    assert row["source_summary"] == "стр. 20 — 1 упомин.; стр. 21 — 1 упомин."
    works[1]["quantity_cell"] = "2 [OCR расходится: 7; проверить]"
    row = build_groups(works)[0]
    assert row["quantity"] is None and row["issues"]


def test_disputed_two_digit_value_cannot_silently_lose_one_digit():
    image, record = numeric_fixture("11", "1 [OCR расходится: 11; проверить]")
    corrected = calibrate(image, record)
    assert "C7–C8=1 |" not in corrected["analysis_text"]
    assert (
        "C7–C8=11 |" in corrected["analysis_text"]
        or "[OCR расходится:" in corrected["analysis_text"]
    )


def test_russian_column_pass_preserves_reading_order_and_does_not_touch_supplier(monkeypatch):
    from types import SimpleNamespace

    from backend.documents.russian_cells import refine

    text = (
        "Строка 1: C1–C2=Наименование | C2–C3=Поставщик |\n"
        "Строка 2: C1–C2=Bozdyxobod | C2–C3=Supplier Ltd. Ø125 | "
    )
    cells = []
    import re

    for i, m in enumerate(re.finditer(r"C\d–C\d=[^|]*\| ?", text)):
        cells.append(
            {
                "start": m.start(),
                "end": m.end(),
                "left": 0 if i % 2 == 0 else 100,
                "right": 95 if i % 2 == 0 else 195,
                "top": 10 if i < 2 else 50,
                "bottom": 40 if i < 2 else 90,
            }
        )
    record = {
        "analysis_text": text,
        "analysis_layout": {"width": 200, "height": 100, "lines": cells},
    }

    def ocr(*args, **kwargs):
        assert args[0][args[0].index("-l") + 1] == "rus"
        tsv = (
            "level\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t60\t14\t20\t20\t95\tØ125\n"
            "5\t1\t1\t1\t12\t15\t45\t20\t95\tВоздуховод\n"
        )
        return SimpleNamespace(stdout=tsv.encode("utf-8"))

    monkeypatch.setattr("backend.documents.russian_cells.subprocess.run", ocr)
    result = refine(Image.new("L", (200, 100), "white"), record)
    assert "Воздуховод Ø125" in result["analysis_text"]
    assert "Supplier Ltd. Ø125" in result["analysis_text"]
    assert record["analysis_text"] == text


def test_ai_cannot_turn_accessory_mentions_into_parent_equipment():
    import asyncio

    from backend.documents.families import assign_work_names

    works = [
        {
            "name": "Дренажный поддон под дефлектор",
            "category": "Вентиляция",
            "unit": "шт.",
            "quantity": 4,
            "page": 20,
            "source_row": 5,
        }
    ]

    async def misleading(*args):
        return {"assignments": [{"index": 0, "work_name": "Установка дефлекторов"}]}

    asyncio.run(assign_work_names(works, {}, misleading))
    assert works[0]["work_name"] == "Дренажный поддон под дефлектор"
    assert works[0]["classification_warning"]
    row = build_groups(works)[0]
    assert row["quantity"] is None and row["issues"]


def test_missing_quantity_in_real_row_remains_visible_instead_of_lowering_total(tmp_path):
    from backend.documents.structured import candidates

    directory = tmp_path / "docling"
    directory.mkdir()
    text = (
        "Строка 1: C1–C2=Наименование | C2–C3=Единица измерения | C3–C4=Количество |\n"
        "Строка 2: C1–C2=Вентиляция |\n"
        "Строка 3: C1–C2=Оборудование |\n"
        "Строка 4: C1–C2=1 Вентилятор радиальный | C2–C3=компл. | C3–C4= |\n"
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
    assert len(works) == 1
    row = build_groups(works)[0]
    assert row["quantity"] is None and row["issues"]
