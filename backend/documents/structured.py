"""Extract every measurable table row before asking AI for work labels."""

import hashlib
import json
import re
from collections import defaultdict

from ..expense_rules import extra_position
from .intent import include_commissioning, requested_categories
from .parsed_tables import CELLS, ROWS, estimate_table
from .russian_cells import restore_names
from .table_context import document_rows
from .work_catalogue import ventilation_type


def insulation_name(category):
    return (
        "Тепловая изоляция матами"
        if category == "Вентиляция"
        else "Теплоизоляция трубопроводов и арматуры"
    )


def read_matrix(path, signature):
    records, tables = {}, {}
    for cached in (path / "docling").glob("page-*.json"):
        record = json.loads(cached.read_text(encoding="utf-8"))
        if record.get("source") != signature:
            continue
        record = restore_names(record)
        number = int(cached.stem.removeprefix("page-"))
        records[number] = record
        tables[number] = estimate_table(record)
    return records, tables, document_rows(tables)


def source_geometry(tables):
    boxes, rows = {}, {}
    for page, table in tables.items():
        if not table:
            continue
        text, layout = table["text"], table["layout"]
        ranges = {int(row[1]): row for row in ROWS.finditer(text)}
        rows[page] = ranges
        if not layout.get("width") or not layout.get("height"):
            continue
        row = iter(ranges.values())
        current = next(row, None)
        for line in sorted(layout.get("lines", []), key=lambda item: item["start"]):
            while current and line["start"] >= current.end():
                current = next(row, None)
            if not current:
                break
            if line["start"] < current.start(2):
                continue
            column = text[line["start"] : line["end"]].split("=", 1)[0]
            boxes.setdefault((page, int(current[1]), column), []).append(
                {
                    "left": line["left"] / layout["width"] * 100,
                    "top": line["top"] / layout["height"] * 100,
                    "width": (line["right"] - line["left"]) / layout["width"] * 100,
                    "height": (line["bottom"] - line["top"]) / layout["height"] * 100,
                }
            )
    return rows, boxes


def row_highlights(page, number, context, contexts, boxes):
    quantity = (
        context.get("surface_column")
        if context.get("role") == "insulation_schedule"
        else context.get("quantity_column")
    )
    own = {
        (page, number, column)
        for column in (context.get("name_column"), context.get("unit_column"), quantity)
        if column
    }
    source = own | {
        (p, row, contexts[p, row].get("name_column"))
        for p, row in context.get("name_locations", ())
        if (p, row) in contexts
    }
    by_page = {}
    for p, row, column in sorted(source, key=lambda item: (item[0], item[1], item[2] or "")):
        if cell_boxes := boxes.get((p, row, column)):
            by_page.setdefault(p, []).extend(cell_boxes)
    return {
        "highlights": by_page.pop(page, []),
        "highlight_pages": [
            {"page": p, "highlights": highlights} for p, highlights in by_page.items()
        ],
    }


def candidates(path, payload):
    records, tables, contexts = read_matrix(path, payload.get("file_hash"))
    rows, boxes = source_geometry(tables)
    requested = requested_categories(payload.get("query", ""))
    commissioning = include_commissioning(payload.get("query", ""))
    works, controls = [], []
    digests, page_digests, duplicate_pages = {}, {}, set()
    scopes = defaultdict(set)
    for (page, _), context in contexts.items():
        if context.get("quantity_cell") or context.get("surface_cell"):
            scopes[page].add((context.get("category") or "", context["section"], context["system"]))
    for page, record in sorted(records.items()):
        if not tables[page]:
            continue
        marker = json.dumps(sorted(scopes[page]), ensure_ascii=False)
        digest = hashlib.sha256((record["text"] + "\n" + marker).encode()).hexdigest()
        page_digests[page] = digest
        if digest in digests:
            duplicate_pages.add(page)
        else:
            digests[digest] = page
    for (page, number), context in sorted(contexts.items()):
        if page in duplicate_pages:
            continue
        name = context.get("name", "").strip()
        cell = context.get("quantity_cell", "").strip()
        unit = context.get("unit_cell", "").strip()
        category = context.get("category") or "Прочее"
        line_name = context.get("dimension_text", "")
        numeric_replacement = "[OCR" in line_name and not re.search(
            r"[а-яё]{3,}", line_name.split(" [OCR")[0], re.I
        )
        name_warning = (not name or numeric_replacement) and bool(re.search(r"\d", cell))
        if name_warning:
            name = f"Страница {page}, строка {number}"
        if context.get("role") == "insulation_schedule":
            name, cell, unit = insulation_name(category), context.get("surface_cell", ""), "м²"
        if extra_position({**context, "name": name}):
            continue
        missing_primary = context.get("named_primary") and context.get("unit_present")
        if (
            not name
            or context.get("component")
            or context.get("ordinal")
            or context.get("structural_note")
            or (not cell and not missing_primary)
        ):
            continue
        # An unreadable unit stays visible for review, rather than silently
        # dropping a measured specification row from the estimate.
        if requested and category not in requested:
            continue
        row = rows.get(page, {}).get(number)
        if row is None or (cell and not re.search(r"\d", cell) and not missing_primary):
            continue
        start = row.start(2)
        quantity_column = context.get(
            "surface_column" if context.get("role") == "insulation_schedule" else "quantity_column"
        )
        columns = {
            context.get("name_column"),
            context.get("unit_column"),
            quantity_column,
        }
        quote = " | ".join(
            cell[0].strip()
            for cell in CELLS.finditer(row[2])
            if f"C{cell[1]}–C{cell[2]}" in columns
        )
        work = {
            "name": name,
            "category": category,
            "unit": unit,
            "quantity": None,
            "unit_cell": unit,
            "unit_present": context.get("unit_present", False),
            "quantity_cell": cell,
            "quantity_column": quantity_column,
            "quantity_warning": (bool(cell) and not re.search(r"\d", cell))
            or any(
                entry["row"] == number and entry["column"] == quantity_column
                for entry in records[page].get("uncertain_numeric_cells", [])
            ),
            "name_warning": name_warning or context.get("name_needs_verification", False),
            "quote": quote,
            "source_row": number,
            "source_start": start,
            "page": page,
            "page_digest": page_digests[page],
            "dimensions": records[page].get("dimensions", {}).get(str(number))
            or records[page].get("dimensions", {}).get(number),
            "dimension_text": context.get("dimension_text", ""),
            "name_locations": context.get("name_locations", ()),
            "source_description": context.get("source_description", name),
            "section": context.get("section", ""),
            "subsection": context.get("subsection", ""),
            "system": context.get("system", ""),
            "item_code": context.get("item_code", ""),
            "table_role": context.get("role"),
            "quantity_basis": "surface_schedule"
            if context.get("role") == "insulation_schedule"
            else "specification",
            **row_highlights(page, number, context, contexts, boxes),
        }
        if re.search(r"секц\s*/\s*квт", unit, re.I) and re.search(r"радиатор", name, re.I):
            # Section count and thermal power summarize the same panel breakdown.
            controls.append(work)
            continue
        standard = ventilation_type(work)
        work["work_name"] = (
            name if context.get("role") == "commissioning" else standard[1] if standard else None
        )
        if context.get("role") == "commissioning" and not commissioning:
            controls.append(work)
        else:
            works.append(work)
    # Insulation material supply and the surface schedule describe the same
    # installation. The surface schedule owns its labour quantity.
    surface_categories = {
        work["category"] for work in works if work["quantity_basis"] == "surface_schedule"
    }
    selected = []
    for work in works:
        standard = ventilation_type(work)
        if (
            (
                (standard and standard[0] == "insulation")
                or work["subsection"].casefold().startswith("теплоизоляционные")
                and re.search(r"минераловат|изоляцион|цилиндр|маты", work["name"], re.I)
            )
            and work["category"] in surface_categories
            and work["quantity_basis"] != "surface_schedule"
        ):
            controls.append(work)
        else:
            selected.append(work)
    return selected, controls
