import hashlib
import io
import re
from collections import Counter
from copy import copy

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill
from openpyxl.worksheet.hyperlink import Hyperlink

from ..analytics import style_sheet
from ..workbook_calculation import cache_formulas
from ..workbook_journal import format_journal, is_journal, journal_row
from .aggregation import notes_with_sources, source_identity, without_position_number
from .extraction import CATEGORIES
from .normalization import build_groups, canonical, unit_value
from .pricing import labour_rates, material_rows
from .work_catalogue import catalogue_order


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
    accepted_locations = {
        source_identity(source)
        for row in confirmed
        for source in row.get("sources", [])
        if source.get("source_row") is not None
    }
    draft = [
        source
        for source in works
        if source_key(source) not in accepted_sources
        and source_identity(source) not in accepted_locations
    ]
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


def make_estimate(content, rows, *, draft=False, download=False):
    categories = {row["id"]: category_for(row) for row in rows}
    order = (
        ["Отопление", *(category for category in CATEGORIES if category != "Отопление")]
        if download
        else CATEGORIES
    )
    rows = sorted(
        rows,
        key=lambda row: (
            order.index(categories[row["id"]]),
            catalogue_order(row["name"]),
            row["name"].casefold(),
        ),
    )
    positions = []
    by_id = {}
    for index, row in enumerate(rows, 1):
        ident = "pdf-" + row["id"]
        category = categories[row["id"]]
        by_id[ident] = row
        notes = notes_with_sources(row)
        positions.append(
            {
                "id": ident,
                "name": without_position_number(row["name"]),
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
    if download:
        references = labour_rates()
        for sheet in journals:
            title = sheet["C2"].value
            if title and title not in book:
                sheet.title = title
            sheet.column_dimensions["A"].hidden = True
            sheet.freeze_panes = "A5"
            for cell in sheet["A"]:
                metadata = journal_row(cell)
                if not metadata or metadata[0] not in by_id:
                    continue
                row = by_id[metadata[0]]
                rate = references.get(
                    (category_for(row), canonical(row["name"]), unit_value(row.get("unit"))[0])
                )
                if rate and row.get("rate") is None:
                    sheet.cell(cell.row, 5).comment = Comment(
                        f"Ориентир {rate[0]} BYN/{row['unit']}. {rate[1]}", "M100"
                    )
        materials = material_rows(rows)
        if materials:
            add_procurement(book, materials)
    if positions and any(row.get("sources") for row in rows):
        sources = book.create_sheet("Источники PDF")
        sources.sheet_state = "hidden"
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
                if download and row.get("issues"):
                    sheet.cell(cell.row, 4).comment = Comment("\n".join(row["issues"]), "M100")
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


def add_procurement(book, materials):
    sheet = book.create_sheet("Закупка")
    sheet.append(
        [
            "Раздел",
            "Материал",
            "Размер и марка",
            "Потребность",
            "Ед. изм.",
            "Цена за ед., BYN",
            "Поставщик",
            "Страница продавца",
            "Телефон",
            "Условия",
            "Проверено",
            "Стр. PDF",
        ]
    )
    for item in materials:
        published = item["offers"]
        for index, offer in enumerate(
            published or [(None, "", "", "", "Запросить цену и сверить характеристики", "")]
        ):
            price, seller, url, phone, terms, checked = offer
            sheet.append(
                [
                    item["category"],
                    item["name"],
                    item["spec"],
                    float(item["quantity"])
                    if item["quantity"] is not None and index == 0
                    else None,
                    item["unit"],
                    float(price) if price is not None else None,
                    seller,
                    ("Открыть предложение" if price is not None else "Запросить цену")
                    if url
                    else None,
                    phone,
                    terms,
                    checked,
                    ", ".join(map(str, sorted(item["pages"]))),
                ]
            )
            if url:
                sheet.cell(sheet.max_row, 8).hyperlink = url
    style_sheet(sheet, 1, [17, 43, 37, 13, 10, 15, 15, 24, 23, 34, 15, 15], money_columns=(6,))
    for cell in sheet["H"][1:]:
        if cell.hyperlink:
            cell.style = "Hyperlink"
