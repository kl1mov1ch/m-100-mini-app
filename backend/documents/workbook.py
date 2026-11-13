import hashlib
import io
import re
from collections import Counter
from copy import copy

import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.worksheet.hyperlink import Hyperlink

from ..analytics import style_sheet
from ..workbook_calculation import cache_formulas
from ..workbook_journal import format_journal, is_journal, journal_row
from .aggregation import notes_with_sources, source_identity
from .extraction import CATEGORIES
from .normalization import build_groups, canonical, unit_value


def estimate_rows(payload):
    groups = payload.get("groups", [])
    works = payload.get("works", [])
    if "works" not in payload:
        return groups
    confirmed = [row for row in groups if row.get("confirmed")]

    def source_key(source):
        return (
            source_identity(source),
            canonical(source.get("original_name") or source.get("name")),
            unit_value(source.get("unit"))[0],
        )

    accepted_sources = {
        source_key(source) for row in confirmed for source in row.get("sources", [])
    }
    draft = [source for source in works if source_key(source) not in accepted_sources]
    compacted = build_groups(draft, [row for row in groups if not row.get("confirmed")])
    accepted_ids = {row["id"] for row in confirmed}
    for row in compacted:
        if row["id"] in accepted_ids:
            row["id"] = hashlib.sha256(("draft-" + row["id"]).encode()).hexdigest()[:24]
    return confirmed + compacted


def category_for(row):
    categories = Counter(source.get("category") for source in row.get("sources", []))
    if row.get("confirmed") and row.get("category") in CATEGORIES:
        return row["category"]
    ranked = [category for category in CATEGORIES[:-1] if categories[category]]
    return (
        max(ranked, key=categories.get)
        if ranked
        else (row["category"] if row.get("category") in CATEGORIES else "Прочее")
    )


def make_estimate(content, rows, *, draft=False):
    categories = {row["id"]: category_for(row) for row in rows}
    rows = sorted(
        rows, key=lambda row: (CATEGORIES.index(categories[row["id"]]), row["name"].casefold())
    )
    positions = []
    by_id = {}
    for index, row in enumerate(rows, 1):
        ident = "pdf-" + row["id"]
        category = categories[row["id"]]
        by_id[ident] = row
        notes = notes_with_sources(row)
        if draft and row.get("issues"):
            notes = "Проверить объём.\n" + notes + "\n" + "\n".join(row["issues"])
        positions.append(
            {
                "id": ident,
                "name": row["name"],
                "section": " · ".join(
                    dict.fromkeys(
                        filter(None, [category, row.get("section"), row.get("subsection")])
                    )
                ),
                "source_sheet": category,
                "source_row": index,
                "unit": row.get("unit") or "",
                "planned": float(row["quantity"]) if row.get("quantity") is not None else None,
                "rate": float(row["rate"]) if row.get("rate") is not None else None,
                "baseline": 0,
                "notes": notes,
                "draft": draft,
            }
        )
    result = format_journal(content, positions, [], {}, [], named_groups=True)
    book = openpyxl.load_workbook(io.BytesIO(result))
    for sheet in list(book):
        if not is_journal(sheet) and not any(
            cell.value is not None for row in sheet for cell in row
        ):
            book.remove(sheet)
    journals = [sheet for sheet in book if is_journal(sheet)]
    if positions and any(row.get("sources") for row in rows):
        sources = book.create_sheet("Источники PDF")
        sources.append(
            [
                "Лист",
                "Позиция",
                "Стр. PDF",
                "Строка",
                "Обозначение",
                "Объём",
                "Ед. изм.",
                "Цитата и условия",
            ]
        )
        for sheet in journals:
            for cell in sheet["A"]:
                metadata = journal_row(cell)
                if not metadata or metadata[0] not in by_id:
                    continue
                row = by_id[metadata[0]]
                if draft and row.get("issues"):
                    sheet.cell(cell.row, 4).fill = PatternFill("solid", fgColor="FFF2D8")
                for source in row.get("sources", []):
                    quote = re.sub(r"\bC\d+–C\d+=", "", source.get("quote", ""))
                    sources.append(
                        [
                            sheet.title,
                            cell.value,
                            source.get("page"),
                            source.get("source_row"),
                            source.get("item_code"),
                            source.get("original_quantity", source.get("quantity")),
                            source.get("original_unit", source.get("unit")),
                            "\n".join(filter(None, [quote.strip(" |"), source.get("notes")])),
                        ]
                    )
                    for source_cell in sources[sources.max_row]:
                        if isinstance(source_cell.value, str):
                            source_cell.data_type = "s"
                    link = sources.cell(sources.max_row, 1)
                    link.hyperlink = Hyperlink(
                        ref=link.coordinate, location=f"'{sheet.title}'!B{cell.row}"
                    )
        style_sheet(sources, 1, [28, 10, 12, 10, 24, 13, 12, 72])
        for cell in sources[1]:
            cell.fill = copy(journals[0]["A1"].fill)
            cell.font = copy(journals[0]["A1"].font)
        for number in range(2, sources.max_row + 1):
            sources.row_dimensions[number].height = min(68, sources.row_dimensions[number].height)
    book.active = journals[0]
    output = io.BytesIO()
    book.save(output)
    return cache_formulas(output.getvalue(), [], original=result)
