"""Extract every measurable table row before asking AI for work labels."""

import hashlib
import json
import re

from .intent import requested_categories
from .parsed_tables import CELLS, ROWS, estimate_table
from .table_context import document_rows
from .work_catalogue import ventilation_type


def read_matrix(path, signature):
    records, tables = {}, {}
    for cached in (path / "docling").glob("page-*.json"):
        record = json.loads(cached.read_text(encoding="utf-8"))
        if record.get("source") != signature:
            continue
        number = int(cached.stem.removeprefix("page-"))
        records[number] = record
        tables[number] = estimate_table(record)
    return records, tables, document_rows(tables)


def candidates(path, payload):
    records, tables, contexts = read_matrix(path, payload.get("file_hash"))
    requested = requested_categories(payload.get("query", ""))
    commissioning = bool(re.search(r"пуск|налад", payload.get("query", ""), re.I))
    works, controls = [], []
    digests, duplicate_pages = {}, set()
    for page, record in sorted(records.items()):
        if not tables[page]:
            continue
        digest = hashlib.sha256(record["text"].encode()).hexdigest()
        if digest in digests:
            duplicate_pages.add(page)
        else:
            digests[digest] = page
    for (page, number), context in sorted(contexts.items()):
        if page in duplicate_pages:
            continue
        table = tables[page]
        name = context.get("name", "").strip()
        cell = context.get("quantity_cell", "").strip()
        unit = context.get("unit_cell", "").strip()
        if context.get("role") == "insulation_schedule":
            name, cell, unit = "Тепловая изоляция матами", context.get("surface_cell", ""), "м²"
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
        category = context.get("category") or "Прочее"
        if requested and category not in requested:
            continue
        row = next((row for row in ROWS.finditer(table["text"]) if int(row[1]) == number), None)
        if row is None or (cell and not re.search(r"\d", cell)):
            continue
        start = row.start(2)
        layout = table["layout"]
        columns = {
            context.get("name_column"),
            context.get("unit_column"),
            context.get("surface_column")
            if context.get("role") == "insulation_schedule"
            else context.get("quantity_column"),
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
            "quantity_cell": cell,
            "quantity_warning": any(
                entry["row"] == number
                and entry["column"]
                == context.get(
                    "surface_column"
                    if context.get("role") == "insulation_schedule"
                    else "quantity_column"
                )
                for entry in records[page].get("uncertain_numeric_cells", [])
            ),
            "quote": quote,
            "source_row": number,
            "source_start": start,
            "page": page,
            "page_digest": hashlib.sha256(records[page]["text"].encode()).hexdigest(),
            "dimensions": records[page].get("dimensions", {}).get(str(number))
            or records[page].get("dimensions", {}).get(number),
            "dimension_text": context.get("dimension_text", ""),
            "name_locations": context.get("name_locations", ()),
            "source_description": context.get("source_description", name),
            "section": context.get("section", ""),
            "subsection": "",
            "quantity_basis": "surface_schedule"
            if context.get("role") == "insulation_schedule"
            else "specification",
            "highlights": [
                {
                    "left": line["left"] / layout["width"] * 100,
                    "top": line["top"] / layout["height"] * 100,
                    "width": (line["right"] - line["left"]) / layout["width"] * 100,
                    "height": (line["bottom"] - line["top"]) / layout["height"] * 100,
                }
                for line in layout.get("lines", [])
                if line["end"] > start
                and line["start"] < row.end()
                and table["text"][line["start"] : line["end"]].split("=", 1)[0] in columns
            ],
        }
        standard = ventilation_type(work)
        work["work_name"] = standard[1] if standard else None
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
            standard
            and standard[0] == "insulation"
            and work["category"] in surface_categories
            and work["quantity_basis"] != "surface_schedule"
        ):
            controls.append(work)
        else:
            selected.append(work)
    return selected, controls
