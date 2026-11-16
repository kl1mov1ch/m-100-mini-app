"""Read isolated PDF table cells with the configured vision model.

The table geometry chooses the field. The model reads symbols, never totals.
All corrections retain the original evidence and are bound to the source hash.
"""

import asyncio
import base64
import hashlib
import io
import json
import re
from bisect import bisect_right
from collections import defaultdict

import httpx
from PIL import Image, ImageDraw, ImageFont

from .. import matcher
from .docling_runner import write_json
from .execution import check_active, run
from .geometry import perimeter
from .glyph_numbers import components
from .normalization import decimal_value, unit_value
from .normalization import numeric_cell as literal
from .parsed_tables import ROWS
from .profile import load_prompt, load_template
from .structured import insulation_name, read_matrix
from .work_catalogue import ventilation_type


def cells(record):
    text = record.get("analysis_text", "")
    rows = [(row.start(), int(row[1])) for row in ROWS.finditer(text)]
    starts = [offset for offset, _ in rows]
    result = []
    for line in record.get("analysis_layout", {}).get("lines", []):
        matched = re.match(r"(C\d+–C\d+)=(.*?)\s*\|\s*$", text[line["start"] : line["end"]], re.S)
        row = bisect_right(starts, line["start"]) - 1
        if matched and row >= 0:
            result.append(
                {**line, "column": matched[1], "value": matched[2].strip(), "row": rows[row][1]}
            )
    return result


def reading_unit(reading, work):
    return unit_value(reading.get("unit") or work.get("unit_cell"))


def response_rows(answer, allowed):
    result, duplicates = {}, set()
    rows = answer.get("rows") if isinstance(answer, dict) else None
    for item in rows if isinstance(rows, list) else []:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item["id"] not in allowed
        ):
            continue
        ident = item["id"]
        if ident in result:
            duplicates.add(ident)
        result[ident] = {
            **{
                key: item[key]
                for key in ("id", "name", "unit", "dimensions", "readable")
                if key in item
            },
            "quantity": literal(item.get("quantity")),
        }
    return {key: item for key, item in result.items() if key not in duplicates}


def needs_dimensions(work):
    standard = ventilation_type(work)
    return bool(standard and standard[0] == "duct" and unit_value(work.get("unit_cell"))[0] == "м")


def dimension_key(value):
    if not isinstance(value, dict) or perimeter(value) is None:
        return None
    keys = ("kind", "diameter_mm") if value.get("kind") == "round" else ("kind", "a_mm", "b_mm")
    sizes = [decimal_value(value.get(key)) for key in keys[1:]]
    if any(size is None for size in sizes):
        return None
    if value.get("kind") == "rectangle":
        sizes.sort()
    return (value["kind"], *(str(size.normalize()) for size in sizes))


def cache_signature(file_hash, cfg, records, *, legacy_profile=None):
    geometry = hashlib.sha256(
        json.dumps(
            {page: record.get("analysis_layout") for page, record in records.items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    prompts = (
        legacy_profile
        or hashlib.sha256(
            (load_prompt("visual") + "\n" + load_prompt("visual_verify")).encode()
        ).hexdigest()
    )
    return hashlib.sha256(
        (file_hash + cfg["base"] + cfg["model"] + prompts + geometry).encode()
    ).hexdigest()


def annotation_only(image):
    """Keep isolated glyphs; do not interpret a fragment of the cell border as a number."""
    width, height = image.size
    inner = image.crop(
        (int(width * 0.12), int(height * 0.12), int(width * 0.88), int(height * 0.88))
    )
    ink = [part for part in components(inner) if len(part[4]) >= 5]
    return bool(ink) and all(
        (left == 0 or top == 0 or right == inner.width or bottom == inner.height)
        and right - left >= inner.width * 0.4
        for left, top, right, bottom, _ in ink
    )


def raster(path, page):
    directory = path / "visual-pages"
    directory.mkdir(exist_ok=True)
    target = directory / f"page-{page}.png"
    if not target.is_file():
        run(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-scale-to",
                "4500",
                "-singlefile",
                "-gray",
                "-png",
                str(path / "source.pdf"),
                str(target.with_suffix("")),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
    return target


def cell_crop(path, page, record, field, images):
    if not field:
        return Image.new("L", (120, 60), "white")
    layout = record.get("analysis_layout", record.get("layout", {}))
    if page not in images:
        if len(images) == 2:
            images.pop(next(iter(images))).close()
        with Image.open(raster(path, page)) as original:
            images[page] = original.convert("L")
    original = images[page]
    sx, sy = original.width / layout["width"], original.height / layout["height"]
    box = (
        max(0, int(field["left"] * sx) - 2),
        max(0, int(field["top"] * sy) - 2),
        min(original.width, int(field["right"] * sx) + 3),
        min(original.height, int(field["bottom"] * sy) + 3),
    )
    return original.crop(box)


def evidence(path, work, records, contexts, page_cells, images=None):
    images = {} if images is None else images
    page, row = work["page"], work["source_row"]
    record, context = records[page], contexts[page, row]
    data = page_cells[page]
    quantity_column = (
        context.get("surface_column")
        if work.get("quantity_basis") == "surface_schedule"
        else context.get("quantity_column")
    )
    find = lambda column: next(
        (item for item in data if item["row"] == row and item["column"] == column), None
    )
    name = find(context.get("name_column"))
    quantity = find(quantity_column)
    if not quantity:
        # A blank cell still has a geometric box: reconstruct it from this row
        # and the quantity column header, rather than guessing a missing number.
        header = next((item for item in data if item["column"] == quantity_column), None)
        anchor = next((item for item in data if item["row"] == row), None)
        if header and anchor:
            quantity = {**header, "top": anchor["top"], "bottom": anchor["bottom"]}
    if not quantity:
        return None
    unit = find(context.get("unit_column"))
    panels = {
        "NAME": cell_crop(path, page, record, name, images),
        "UNIT": cell_crop(path, page, record, unit, images),
        "QTY": cell_crop(path, page, record, quantity, images),
    }
    if dimension_column := context.get("dimension_column"):
        panels["DIM"] = cell_crop(path, page, record, find(dimension_column), images)
    if work.get("quantity_basis") != "surface_schedule":
        fragments = []
        for anchor_page, anchor_row in context.get("name_locations", ())[:4]:
            if (anchor_page, anchor_row) == (page, row):
                continue
            column = contexts[anchor_page, anchor_row]["name_column"]
            anchor = next(
                (
                    item
                    for item in page_cells[anchor_page]
                    if item["row"] == anchor_row and item["column"] == column
                ),
                None,
            )
            if anchor:
                crop = cell_crop(path, anchor_page, records[anchor_page], anchor, images)
                crop.thumbnail((1200, 72))
                fragments.append(crop)
        if fragments:
            title = Image.new(
                "L", (max(i.width for i in fragments), sum(i.height for i in fragments)), "white"
            )
            top = 0
            for fragment in fragments:
                title.paste(fragment, (0, top))
                top += fragment.height
            panels["ANCHOR"] = title
    return panels


def panel_image(items, verification=False):
    width, height = (1440, 265)
    canvas = Image.new("L", (width, height * len(items)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, item in enumerate(items):
        offset = index * height
        draw.text((8, offset + 2), item["id"], fill=0, font=font)
        positions = (
            [("QTY", 10, 380), ("UNIT", 410, 260), ("DIM", 720, 700), ("NAME", 10, 1400)]
            if verification
            else [
                ("NAME", 10, 900),
                ("UNIT", 930, 160),
                ("QTY", 1120, 300),
                ("ANCHOR", 10, 900),
                ("DIM", 930, 490),
            ]
        )
        for label, left, maximum in positions:
            if label not in item["panels"]:
                continue
            top = offset + (
                115
                if (verification and label == "NAME")
                or (not verification and label in {"ANCHOR", "DIM"})
                else 24
            )
            draw.text((left, top), label, fill=0, font=font)
            crop = item["panels"][label].copy()
            crop.thumbnail((maximum, 125 if label == "ANCHOR" else (95 if verification else 62)))
            canvas.paste(crop, (left, top + 23))
        draw.line((0, offset + height - 1, width, offset + height - 1), fill=180)
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def dimension_image(items):
    canvas = Image.new("L", (1300, 157 * len(items)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, item in enumerate(items):
        top = index * 157
        draw.text((8, top + 3), item["id"], fill=0, font=font)
        for label, left, width in [("NAME", 10, 980), ("DIM", 1000, 285)]:
            panel = item["panels"].get(label)
            if panel:
                crop = panel.copy()
                crop.thumbnail((width, 112))
                canvas.paste(crop, (left, top + 28))
        draw.line((0, top + 156, 1300, top + 156), fill=180)
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def apply_reading(work, item, signature):
    if item.get("structural_note_only") is True:
        return {**work, "structural_note_only": True}
    quantity = literal(item.get("quantity"))
    unit = str(item.get("unit") or work.get("unit_cell") or "").strip()[:40]
    if item.get("readable") is not True or quantity is None or not unit:
        return {**work, "quantity_warning": True}
    name = str(item.get("name") or work["name"]).strip()[:500]
    if work.get("quantity_basis") == "surface_schedule":
        name, unit = insulation_name(work.get("category")), "м²"
    result = {
        **work,
        "original_name": work.get("original_name") or work["name"],
        "ocr_quantity": work.get("quantity_cell"),
        "ocr_unit": work.get("unit_cell"),
        "name": name,
        "quantity_cell": quantity,
        "unit_cell": unit,
        "unit": unit,
        "quantity_warning": False,
        "work_name": name if work.get("table_role") == "commissioning" else None,
        "visual_verified": True,
        "visual_source_hash": signature,
        "visual_reading": item,
    }
    dimensions = item.get("dimensions")
    if isinstance(dimensions, dict) and perimeter(dimensions) is not None:
        result["dimensions"] = dimensions
    standard = None if work.get("table_role") == "commissioning" else ventilation_type(result)
    if not standard and work.get("continuation_of") and work.get("table_role") != "commissioning":
        parent = ventilation_type({**work, "name": work["continuation_of"]})
        rule = next(
            (
                row.get("continuation_pattern")
                for row in load_template()["works"]
                if parent and row["id"] == parent[0]
            ),
            None,
        )
        if rule and re.search(rule, name, re.I):
            standard = parent
    if standard:
        result["work_name"] = standard[1]
    if standard and standard[0] == "duct" and unit_value(unit)[0] == "м":
        result["dimensions"] = (
            dimensions
            if isinstance(dimensions, dict) and perimeter(dimensions) is not None
            else None
        )
        result["visual_dimensions_required"] = True
    result.pop("classification_warning", None)
    if work.get("name_warning") and not re.search(r"[а-яё]{3,}", str(item.get("name") or ""), re.I):
        result["classification_warning"] = "Уточните наименование по строке PDF"
    return result


def calibrated_cell(work, record):
    return {"row": work.get("source_row"), "column": work.get("quantity_column")} in record.get(
        "verified_numeric_cells", []
    )


def local_reading(work, record):
    raw = str(work.get("quantity_cell") or "").strip()
    value = literal(raw)
    unit, factor = unit_value(work.get("unit_cell"))
    if (
        not calibrated_cell(work, record)
        or work.get("quantity_warning")
        or work.get("name_warning")
        or not value
        or "/" in value
        or not re.fullmatch(r"(?:\d+|\d{1,3}(?:[ \u00a0]\d{3})+)(?:[,.]\d+)?", raw)
        or not factor
        or not (work.get("unit_present") or work.get("quantity_basis") == "surface_schedule")
        or not re.search(r"[а-яё]{3,}", work["name"], re.I)
    ):
        return False
    # A missing comma can change reported length/area by orders of magnitude.
    if unit == "шт.":
        return bool(re.fullmatch(r"0|[1-9]\d*", value))
    if "," not in value:
        return False
    if needs_dimensions(work):
        dimensions = work.get("dimensions")
        return bool(
            dimension_key(dimensions)
            and perimeter(dimensions) == perimeter(None, work.get("dimension_text", ""))
        )
    return True


def page_batches(items):
    pages = defaultdict(list)
    for item in items:
        pages[item[1]["page"]].append(item)
    for rows in pages.values():
        for start in range(0, len(rows), 8):
            yield rows[start : start + 8]


async def resolve(path, payload, settings, complete, report, *, page_report=None):
    records, _, contexts = read_matrix(path, payload.get("file_hash"))
    works = [dict(work) for work in payload.get("works", [])]
    candidates = [
        work
        for work in works
        if records.get(work.get("page"), {}).get("method") == "docling+tesseract"
        and (work.get("page"), work.get("source_row")) in contexts
    ]
    if not candidates:
        return works
    for work in candidates:
        context = contexts[work["page"], work["source_row"]]
        if not context.get("named_primary") and context.get("name_location"):
            work["continuation_of"] = context["name"]
    cfg = matcher.provider(settings)
    stamp = cache_signature(payload["file_hash"], cfg, records)
    cache_path = path / "visual-rows.json"
    saved = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    cache = saved.get("rows", {}) if saved.get("signature") == stamp else {}
    by_location = {(work["page"], work["source_row"]): i for i, work in enumerate(works)}
    pending, done = [], 0
    for work in candidates:
        ident = f"P{work['page']}-R{work['source_row']}"
        if ident in cache and (
            cache[ident].get("structural_note_only") is True
            or (
                cache[ident].get("readable") is True
                and literal(cache[ident].get("quantity")) is not None
            )
        ):
            index = by_location[work["page"], work["source_row"]]
            works[index] = apply_reading(work, cache[ident], payload["file_hash"])
            done += 1
        elif local_reading(work, records[work["page"]]):
            index = by_location[work["page"], work["source_row"]]
            works[index] = {**work, "local_verified": True}
            done += 1
        else:
            pending.append((ident, work))
    report(done, len(candidates), works)
    evidence_pages = {work["page"] for _, work in pending}
    for _, work in pending:
        context = contexts[work["page"], work["source_row"]]
        evidence_pages.update(page for page, _ in context.get("name_locations", ())[:4])
    page_cells = {page: cells(records[page]) for page in evidence_pages}

    async def request(prompt, content, limit):
        for attempt in range(3):
            try:
                return await complete(
                    load_prompt(prompt), content, {**settings, "response_token_limit": limit}
                )
            except (httpx.HTTPError, ValueError) as error:
                if (
                    isinstance(error, httpx.HTTPStatusError)
                    and error.response.status_code not in {408, 429}
                    and error.response.status_code < 500
                ):
                    raise
                if attempt == 2:
                    raise
                check_active()
                await asyncio.sleep(0.5 * (attempt + 1))

    def prepare(part):
        items = []
        notes = {}
        images = {}
        for ident, work in part:
            check_active()
            panels = evidence(path, work, records, contexts, page_cells, images)
            if panels:
                if (
                    work.get("continuation_of")
                    and not work.get("unit_cell")
                    and work.get("quantity_warning")
                    and annotation_only(panels["QTY"])
                ):
                    notes[ident] = {"structural_note_only": True}
                    continue
                items.append({"id": ident, "work": work, "panels": panels})
        for image in images.values():
            image.close()
        return items, notes

    preparation = asyncio.Lock()

    async def batch(part):
        async with preparation:
            items, notes = await asyncio.to_thread(prepare, part)
        if not items:
            return notes, part
        metadata = [
            {
                "id": item["id"],
                "anchor_name": item["work"].get("source_description") or item["work"]["name"],
                "inherited_unit": item["work"].get("unit_cell"),
                "quantity_basis": item["work"].get("quantity_basis"),
                "needs_dimensions": needs_dimensions(item["work"]),
            }
            for item in items
        ]
        content = [
            {"type": "text", "text": json.dumps({"rows": metadata}, ensure_ascii=False)},
            {"type": "image_url", "image_url": {"url": panel_image(items), "detail": "high"}},
        ]
        first = response_rows(
            await request("visual", content, 6000),
            {item["id"] for item in items},
        )
        verify = [
            item
            for item in items
            if item["id"] in first
            and (
                item["work"].get("quantity_warning")
                or not calibrated_cell(item["work"], records[item["work"]["page"]])
                or not item["work"].get("unit_present")
                or needs_dimensions(item["work"])
                or literal(item["work"].get("quantity_cell")) is None
                or literal(item["work"].get("quantity_cell")) != first[item["id"]].get("quantity")
                or reading_unit(first[item["id"]], item["work"])
                != unit_value(item["work"].get("unit_cell"))
            )
        ]
        if verify:
            second_content = [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "rows": [
                                {
                                    "id": item["id"],
                                    "inherited_unit": item["work"].get("unit_cell"),
                                    "needs_dimensions": needs_dimensions(item["work"]),
                                }
                                for item in verify
                            ]
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": panel_image(verify, True), "detail": "high"},
                },
            ]
            second = response_rows(
                await request("visual_verify", second_content, 3000),
                {item["id"] for item in verify},
            )
            for item in verify:
                ident = item["id"]
                if (
                    ident not in second
                    or second[ident].get("readable") is not True
                    or first[ident].get("quantity") != second[ident].get("quantity")
                    or reading_unit(first[ident], item["work"])
                    != reading_unit(second[ident], item["work"])
                ):
                    first[ident] = {"readable": False, "quantity": None}
                elif needs_dimensions(item["work"]) and dimension_key(
                    first[ident].get("dimensions")
                ) != dimension_key(second[ident].get("dimensions")):
                    calibrated = item["work"].get("dimensions")
                    key = dimension_key(calibrated)
                    first[ident]["dimensions"] = (
                        calibrated
                        if key is not None
                        and key
                        in {
                            dimension_key(first[ident].get("dimensions")),
                            dimension_key(second[ident].get("dimensions")),
                        }
                        else None
                    )
        return {**first, **notes}, part

    limiter = asyncio.Semaphore(4)

    async def limited(part):
        async with limiter:
            return await batch(part)

    tasks = [asyncio.create_task(limited(part)) for part in page_batches(pending)]
    try:
        for future in asyncio.as_completed(tasks):
            result, part = await future
            for ident, work in part:
                answer = result.get(ident, {"readable": False, "quantity": None})
                cache[ident] = answer
                index = by_location[work["page"], work["source_row"]]
                works[index] = apply_reading(work, answer, payload["file_hash"])
                done += 1
            check_active()
            write_json(cache_path, {"signature": stamp, "rows": cache})
            if page_report:
                page_report(part[0][1]["page"])
            report(done, len(candidates), works)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # A broader reading can get the number right and still miss a size.
    # Re-read just the dimension cell before sending a duct to manual review.
    revision = hashlib.sha256(load_prompt("visual_dimensions").encode()).hexdigest()[:16]
    sizes = []
    for original in candidates:
        page, row = original["page"], original["source_row"]
        ident = f"P{page}-R{row}"
        index = by_location[page, row]
        work = works[index]
        saved = cache.get(ident, {})
        if (
            work.get("visual_verified")
            and work.get("visual_dimensions_required")
            and dimension_key(work.get("dimensions")) is None
            and saved.get("dimension_repair_revision") != revision
        ):
            sizes.append((ident, index, original))
    if sizes and not page_cells:
        page_cells = {page: cells(record) for page, record in records.items()}
    for start in range(0, len(sizes), 8):
        items = []
        for ident, index, original in sizes[start : start + 8]:
            check_active()
            panels = evidence(path, original, records, contexts, page_cells)
            if panels:
                items.append({"id": ident, "index": index, "original": original, "panels": panels})
        if not items:
            continue

        async def read_sizes(batch, pass_number):
            return response_rows(
                await request(
                    "visual_dimensions",
                    [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"pass": pass_number, "ids": [i["id"] for i in batch]}
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": dimension_image(batch), "detail": "high"},
                        },
                    ],
                    3000,
                ),
                {i["id"] for i in batch},
            )

        first = await read_sizes(items, 1)
        verify = [
            item
            for item in items
            if dimension_key(first.get(item["id"], {}).get("dimensions")) is not None
            and dimension_key(first[item["id"]]["dimensions"])
            != dimension_key(item["original"].get("dimensions"))
        ]
        second = await read_sizes(list(reversed(verify)), 2) if verify else {}
        for item in items:
            ident = item["id"]
            found = first.get(ident, {}).get("dimensions")
            key = dimension_key(found)
            answer = {**cache[ident], "dimension_repair_revision": revision}
            if key is not None and key in {
                dimension_key(item["original"].get("dimensions")),
                dimension_key(second.get(ident, {}).get("dimensions")),
            }:
                answer["dimensions"] = found
                works[item["index"]] = apply_reading(item["original"], answer, payload["file_hash"])
            cache[ident] = answer
        write_json(cache_path, {"signature": stamp, "rows": cache})
        report(done, len(candidates), works)
    return [work for work in works if not work.get("structural_note_only")]
