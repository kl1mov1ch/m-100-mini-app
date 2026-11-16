import hashlib
import io
import re
from collections import Counter, defaultdict
from copy import copy
from textwrap import TextWrapper

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.views import Selection

from ..analytics import style_sheet
from ..expense_rules import extra_position
from ..workbook_calculation import cache_formulas
from ..workbook_journal import format_journal, is_journal, journal_row
from .aggregation import notes_with_sources, source_identity, without_position_number
from .extraction import CATEGORIES
from .normalization import build_groups, canonical, unit_value
from .pricing import material_rows
from .work_catalogue import catalogue_order


def estimate_rows(payload):
    groups = [row for row in payload.get("groups", []) if not extra_position(row)]
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
        if not extra_position(source)
        and source_key(source) not in accepted_sources
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


def fit_cells(sheet, widths, row_numbers=None):
    for column, (minimum, maximum) in widths.items():
        longest = max(
            (
                max(map(len, cell.value.splitlines()), default=0)
                for cell in sheet[get_column_letter(column)]
                if isinstance(cell.value, str) and cell.data_type == "s"
            ),
            default=0,
        )
        sheet.column_dimensions[get_column_letter(column)].width = min(
            maximum, max(minimum, longest + 3)
        )
    wrappers = {
        column: TextWrapper(width=max(5, int(dim.width * 0.88) - 2))
        for column in range(1, sheet.max_column + 1)
        if not (dim := sheet.column_dimensions[get_column_letter(column)]).hidden
    }
    for number in row_numbers if row_numbers is not None else range(1, sheet.max_row + 1):
        lines = 1
        for column, wrapper in wrappers.items():
            cell = sheet.cell(number, column)
            if not isinstance(cell.value, str) or cell.data_type != "s":
                continue
            alignment = copy(cell.alignment)
            alignment.wrap_text = True
            cell.alignment = alignment
            lines = max(
                lines,
                sum(max(1, len(wrapper.wrap(part))) for part in cell.value.split("\n")),
            )
        base = sheet.row_dimensions[number].height or 0
        sheet.row_dimensions[number].height = min(409, max(23, base, 16 * lines + 6))


def download_controls(payload):
    return [row for row in payload.get("controls", []) if row.get("table_role") != "commissioning"]


def downloadable_estimate(rows, payload, *, draft=False):
    blank = io.BytesIO()
    openpyxl.Workbook().save(blank)
    return make_estimate(
        blank.getvalue(), rows, draft=draft, download=True, controls=download_controls(payload)
    )


def make_estimate(content, rows, *, draft=False, download=False, controls=()):
    rows = [row for row in rows if not extra_position(row)]
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
            row.get("subsection") == "Пусконаладочные работы",
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
        if download:
            context = " · ".join(
                dict.fromkeys(
                    value
                    for value in (row.get("section"), row.get("subsection"))
                    if value and value not in {category, "Без раздела"}
                )
            )
            notes = "\n".join(filter(None, (context, notes)))
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
        for sheet in journals:
            title = sheet["C2"].value
            if title and title not in book:
                sheet.title = title
            sheet.column_dimensions["A"].hidden = True
            sheet.sheet_view.selection = [Selection(activeCell="B5", sqref="B5")]
            sheet.freeze_panes = "A5"
            visible_rows = [1]
            for cell in sheet["A"]:
                metadata = journal_row(cell)
                if not metadata or metadata[0] not in by_id:
                    continue
                row = by_id[metadata[0]]
                visible_rows.append(cell.row)
                if note := sheet.cell(cell.row, 2).comment:
                    sheet.cell(cell.row, 10, note.text).data_type = "s"
                if draft and (suggestion := row.get("rate_suggestion")) and not row["confirmed"]:
                    sheet.cell(cell.row, 5).comment = Comment(
                        f"Предложено из общего справочника: {suggestion['name']}. Проверьте ставку.",
                        "M100",
                    )
            fit_cells(
                sheet,
                {
                    2: (42, 68),
                    3: (9, 14),
                    4: (14, 19),
                    5: (15, 20),
                    6: (16, 20),
                    7: (14, 18),
                    8: (16, 22),
                    9: (17, 22),
                    10: (35, 66),
                },
                visible_rows,
            )
        materials = material_rows(
            [
                *rows,
                *(
                    {"name": source["name"], "category": source["category"], "sources": [source]}
                    for source in controls
                ),
            ]
        )
        if materials:
            add_procurement(book, materials)
    if positions and (controls or any(row.get("sources") for row in rows)):
        sources = book.create_sheet("Источники PDF")
        sources.sheet_state = "visible" if download else "hidden"
        sources.append(
            [
                "Лист",
                "Позиция",
                "Стр. PDF",
                "Строка",
                "Обозначение",
                "Объём",
                "Ед. изм.",
                "Раздел и подраздел",
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
                            " · ".join(
                                dict.fromkeys(
                                    filter(None, (source.get("section"), source.get("subsection")))
                                )
                            ),
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
        for source in sorted(controls, key=lambda row: (row["page"], row.get("source_row") or 0)):
            sources.append(
                [
                    source["category"],
                    "Справочно",
                    source["page"],
                    source.get("source_row"),
                    source.get("item_code"),
                    source.get("quantity_cell"),
                    source.get("unit_cell"),
                    " · ".join(
                        dict.fromkeys(
                            filter(None, (source.get("section"), source.get("subsection")))
                        )
                    ),
                    re.sub(r"\bC\d+–C\d+=", "", source.get("quote", "")).strip(" |"),
                ]
            )
            for cell in sources[sources.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        style_sheet(sources, 1, [24, 10, 12, 10, 24, 13, 12, 26, 70])
        for cell in sources[1]:
            cell.fill = copy(journals[0]["A1"].fill)
            cell.font = copy(journals[0]["A1"].font)
        fit_cells(sources, {1: (16, 28), 5: (20, 37), 8: (24, 36), 9: (48, 82)})
        divide_auxiliary_columns(sources)
    book.active = journals[0]
    output = io.BytesIO()
    book.save(output)
    return cache_formulas(output.getvalue(), [], original=result)


def divide_auxiliary_columns(sheet, *, skip_rows=()):
    divider = Side(style="thin", color="D2DDE8")
    header_divider = Side(style="thin", color="5C738A")
    for row in sheet.iter_rows():
        number = row[0].row
        if number in skip_rows:
            continue
        for cell in row:
            border = copy(cell.border)
            border.right = header_divider if number == 1 else divider
            cell.border = border


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
            "Страница продавца",
            "Условия",
            "Проверено",
            "Стр. PDF",
        ]
    )
    vendors = defaultdict(list)
    contacts = defaultdict(dict)
    names = {}
    for item in materials:
        offers = item["offers"] or [(None, "", "", "", "Уточнить цену и характеристики", "")]
        lowest = min((offer[0] for offer in offers if offer[0] is not None), default=None)
        for price, seller, url, phone, terms, checked in offers:
            key = " ".join(seller.casefold().split())
            names.setdefault(key, seller)
            if phone:
                contacts[key].setdefault(re.sub(r"\D", "", phone), phone)
            vendors[key].append((item, price, url, terms, checked, lowest))
    headers = []
    best_prices = []
    for key in sorted(vendors, key=lambda value: (not value, value)):
        sheet.append(
            [
                names[key] or "Поставщик не подобран",
                None,
                None,
                None,
                None,
                None,
                ", ".join(contacts[key].values()) or None,
            ]
        )
        headers.append(sheet.max_row)
        for item, price, url, terms, checked, lowest in vendors[key]:
            sheet.append(
                [
                    item["category"],
                    item["name"],
                    item["spec"],
                    float(item["quantity"]) if item["quantity"] is not None else None,
                    item["unit"],
                    float(price) if price is not None else None,
                    ("Открыть предложение" if price is not None else "Запросить цену")
                    if url
                    else None,
                    terms,
                    checked,
                    ", ".join(map(str, sorted(item["pages"]))),
                ]
            )
            if url:
                sheet.cell(sheet.max_row, 7).hyperlink = url
            if price is not None and price == lowest:
                best_prices.append(sheet.max_row)
    style_sheet(sheet, 1, [17, 43, 37, 13, 10, 17, 24, 34, 15, 15], money_columns=(6,))
    sheet.auto_filter.ref = None
    fit_cells(
        sheet, {1: (17, 23), 2: (38, 60), 3: (32, 48), 7: (21, 27), 8: (27, 52), 10: (15, 24)}
    )
    for cell in sheet["G"][1:]:
        if cell.hyperlink:
            cell.font = Font(name="Calibri", size=11, color="2268BB", underline="single")
    for row in headers:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        sheet.merge_cells(start_row=row, start_column=7, end_row=row, end_column=10)
        for cell in sheet[row]:
            cell.fill = PatternFill("solid", fgColor="E8F2FB")
            cell.font = Font(name="Calibri", size=11, color="21344A", bold=True)
            cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
        sheet.row_dimensions[row].height = 26
    header_rows = set(headers)
    for row in sheet.iter_rows():
        number = row[0].row
        if number in header_rows:
            continue
        color = "21344A" if number == 1 else "F5F8FC" if number % 2 == 0 else "FFFFFF"
        for cell in row:
            cell.fill = PatternFill("solid", fgColor=color)
    for row in best_prices:
        cell = sheet.cell(row, 6)
        cell.fill = PatternFill("solid", fgColor="E6F4EC")
        cell.font = Font(name="Calibri", size=11, color="24634C", bold=True)
    divide_auxiliary_columns(sheet, skip_rows=header_rows)
