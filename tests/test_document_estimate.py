import asyncio
import io

import openpyxl

from backend import bitrix
from backend.documents import extraction
from backend.documents.aggregation import estimate_name
from backend.documents.docling_runner import structured_table, valid_record
from backend.documents.normalization import build_groups
from backend.documents.parsed_tables import estimate_table
from backend.documents.workbook import estimate_rows, make_estimate
from backend.workbook_journal import format_journal


def source(name, row, unit="м²", quantity=10, category="Вентиляция"):
    return {
        "name": name,
        "source_row": row,
        "page": 20,
        "quote": f"П{row}: {name} {quantity} {unit}",
        "unit": unit,
        "quantity": quantity,
        "category": category,
    }


def test_column_headers_are_required_and_excluded_coordinates_do_not_leak():
    text = "Схема воздуховода: 999 м\nТаблица: ячейки по строкам и колонкам.\n"
    text += "Строка 1: C1–C2=Наименование | C2–C3=Количество | C3–C4=Единица измерения |\n"
    text += "Строка 2: C1–C2=Воздуховод | C2–C3=10 | C3–C4=м² |\n"
    text += "Строка 3: C1–C2=Труба | C2–C3=20 | C3–C4=м |\n"
    text += "Строка 4: C8–C9=За рамкой: 999 м |\n"
    begin = text.index("Воздуховод")
    table = estimate_table(
        {
            "analysis_text": text,
            "analysis_layout": {
                "lines": [
                    {"start": begin, "end": begin + 10, "left": 10, "top": 30},
                    {"start": text.index("За рамкой"), "end": len(text), "left": 80, "top": 90},
                ]
            },
        }
    )
    assert table and "999" not in table["text"] and table["rows"] == [1, 2, 3]
    assert len(table["layout"]["lines"]) == 1
    line = table["layout"]["lines"][0]
    assert table["text"][line["start"] : line["end"]] == "Воздуховод"
    assert (
        estimate_table({"text": "Спецификация оборудования. Наименование Количество Единица"})
        is None
    )
    assert (
        estimate_table({"analysis_text": text.replace("Наименование", "Номер помещения")}) is None
    )


def test_sizes_and_supplied_accessories_do_not_split_the_labour_line():
    name = (
        "Монтаж вентилятора радиального взрывозащищенного L=350 м³/ч, в комплекте: гибкая вставка"
    )
    assert estimate_name(source(name, 1)) == "Монтаж вентиляторов (радиальных, взрывозащищённых)"
    works = [
        source("Монтаж воздуховодов 200х300 мм", 1),
        source("Монтаж воздуховодов 400х600 мм", 2),
        source("Монтаж воздуховодов 600х600 мм", 3, unit=None),
    ]
    rows = build_groups(works)
    assert len(rows) == 1 and len(rows[0]["sources"]) == 3
    assert rows[0]["quantity"] is None and rows[0]["issues"] and rows[0]["unit"] == "м²"
    # Square and linear metres can never be added together.
    assert len(build_groups([*works, source("Монтаж воздуховодов", 4, unit="м")])) == 3


def test_merged_table_name_cells_provide_context_for_dimension_rows():
    text = "Строка 1: C1–C2=Наименование | C2–C3=Количество | C3–C4=Единица измерения |\n"
    text += "Строка 2: C1–C2=Воздуховод стальной | C2–C3=10 | C3–C4=м² |\n"
    text += "Строка 3: C1–C2=200х300 | C2–C3=20 | C3–C4=м² |\n"
    table = estimate_table({"analysis_text": text})
    assert table["row_names"][2] == table["row_names"][3] == "Воздуховод стальной"


def test_unit_cell_overrides_an_ai_guess(monkeypatch):
    text = "Таблица: ячейки по строкам и колонкам.\n"
    text += "Строка 1: C1–C2=Наименование | C2–C3=Количество | C3–C4=Единица измерения |\n"
    text += "Строка 2: C1–C2=Труба | C2–C3=12 | C3–C4=м |\n"
    replies = iter(
        [
            {
                "works": [
                    {
                        "name": "Монтаж трубы",
                        "category": "Отопление",
                        "source_row": 2,
                        "quantity_column": "C2–C3",
                        "quantity": 12,
                        "unit": "шт.",
                    }
                ]
            },
            {"accepted": [0]},
        ]
    )

    async def complete(*args):
        return next(replies)

    monkeypatch.setattr(extraction.matcher, "complete", complete)
    works, _ = asyncio.run(extraction.propose(text, 19, {}, "Отопление"))
    assert works[0]["unit"] == "м" and works[0]["quantity"] == 12


def test_native_cell_geometry_uses_text_coordinates_without_numeric_ocr(monkeypatch):
    from PIL import Image, ImageDraw

    image = Image.new("L", (1000, 1000), "white")
    draw = ImageDraw.Draw(image)
    for y in range(100, 901, 100):
        draw.line((50, y, 950, y), fill=0, width=2)
    for x in (50, 250, 450, 650, 950):
        draw.line((x, 100, x, 900), fill=0, width=2)
    text, lines = "", []
    for y in range(150, 851, 100):
        for x in (150, 350, 550, 800):
            start = len(text)
            text += "12 "
            lines.append(
                {
                    "start": start,
                    "end": start + 2,
                    "left": x,
                    "right": x + 10,
                    "top": y,
                    "bottom": y + 10,
                }
            )
    monkeypatch.setattr(
        "backend.documents.docling_runner.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Native numbers must not go through OCR")
        ),
    )
    result = structured_table(
        image,
        {"text": text, "layout": {"width": 1000, "height": 1000, "lines": lines}},
        verify_numbers=False,
    )
    assert "Строка 1:" in result["analysis_text"] and len(result["analysis_layout"]["lines"]) == 32
    assert valid_record(
        {"source": "hash", "engine": "docling-2.150.0-v2", "method": "docling+tesseract"}, "hash"
    )
    assert not valid_record({"source": "hash", "engine": "docling-2.150.0-v2"}, "hash")


def test_export_preserves_confirmed_edits_and_uses_the_working_journal_format():
    first = source("Монтаж воздуховодов 200х300 мм", 1)
    second = source("Монтаж воздуховодов 400х600 мм", 2)
    accepted = build_groups([first])[0]
    accepted.update(
        confirmed=True,
        name="Принятое мастером название",
        rate="3",
        quantity="12",
        notes="Правка мастера",
    )
    rows = estimate_rows({"works": [first, second], "groups": [accepted]})
    assert rows[0] == accepted and rows[1]["id"] != accepted["id"]
    assert len(rows[1]["id"]) == 24
    repaired = {**first, "original_name": first["name"], "name": "Воздуховод стальной"}
    assert estimate_rows({"works": [repaired], "groups": [accepted]}) == [accepted]
    other = build_groups([source("Монтаж трубы Ø25 мм", 3, unit="м", category="Отопление")])[0]
    blank = io.BytesIO()
    openpyxl.Workbook().save(blank)
    content = make_estimate(blank.getvalue(), [*rows, other], draft=True)
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Работы · Вентиляция", "Работы · Отопление", "Источники PDF"]
    for sheet in list(book)[:2]:
        assert sheet.freeze_panes == "J5" and sheet["J1"].value == "Примечание"
        assert sheet["B5"].comment and sheet["A1"].fill.fgColor.rgb[-6:] == "21344A"
    values = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    assert values["Работы · Отопление"]["F5"].value in (None, "")
    assert values["Работы · Отопление"]["D5"].value == 10
    # Confirmed input produces a directly usable Bitrix workbook with dates.
    accepted["category"] = "Вентиляция"
    ready = make_estimate(blank.getvalue(), [accepted])
    catalogue = bitrix.read_workbook(ready)["positions"]
    day = "2026-11-13"
    updated = format_journal(
        ready,
        catalogue,
        [{"item_id": catalogue[0]["id"], "date": day, "quantity": 2}],
        {day: 2},
        [],
    )
    sheet = openpyxl.load_workbook(io.BytesIO(updated)).active
    assert sheet["J3"].value.date().isoformat() == day and sheet["K1"].value == "Примечание"
    assert "Правка мастера" in sheet["B5"].comment.text
    assert openpyxl.load_workbook(io.BytesIO(updated), data_only=True).active["H5"].value == 6
