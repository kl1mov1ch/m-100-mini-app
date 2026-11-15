import json
import os
import re
import subprocess
from pathlib import Path

from .docling_runner import ENGINE, valid_record
from .execution import run
from .parsed_tables import estimate_table


def table_works(path, payload):
    """Filter saved draft evidence without modifying a job or its source files."""
    if payload.get("engine") != "docling":
        return payload.get("works", [])
    from .intent import include_commissioning, select_works
    from .structured import insulation_name, read_matrix, row_highlights, source_geometry

    _, tables, contexts = read_matrix(path, payload.get("file_hash"))
    _, boxes = source_geometry(tables)
    result = []
    for work in payload.get("works", []):
        table = tables.get(work.get("page"))
        if work.get("page") not in tables:
            result.append(work)
            continue
        if not table or work.get("source_row") not in table["rows"]:
            continue
        context = contexts.get((work["page"], work["source_row"]), {})
        if context.get("role") == "commissioning" and not include_commissioning(
            payload.get("query", "")
        ):
            continue
        if context.get("component") or context.get("structural_note"):
            continue
        work = {
            **work,
            "category": context.get("category") or work.get("category"),
            "section": context.get("section") or work.get("section") or "",
            "subsection": context.get("subsection") or work.get("subsection") or "",
            "item_code": context.get("item_code") or work.get("item_code") or "",
            "table_role": context.get("role"),
            "source_description": context.get("source_description")
            or work.get("source_description"),
        }
        geometry = row_highlights(work["page"], work["source_row"], context, contexts, boxes)
        if geometry["highlights"] or geometry["highlight_pages"]:
            work.update(geometry)
        if work.get("visual_verified") and work.get("visual_source_hash") == payload.get(
            "file_hash"
        ):
            result.append(work)
            continue
        work = {
            **work,
            "quantity_cell": context.get("quantity_cell"),
            "unit_cell": context.get("unit_cell"),
        }
        if context.get("role") == "insulation_schedule":
            name = insulation_name(work.get("category"))
            work = {
                **work,
                "original_name": work.get("original_name") or work["name"],
                "name": name,
                "work_name": work.get("work_name") if work["name"] == name else None,
                "quantity_basis": "surface_schedule",
                "unit_cell": "м²",
                "quantity_cell": context.get("surface_cell"),
            }
        elif context.get("name"):
            work = {
                **work,
                "original_name": work.get("original_name") or work["name"],
                "name": context["name"],
                "work_name": work.get("work_name") if work["name"] == context["name"] else None,
            }
        if not re.search(
            r"[а-яА-Яa-zA-Z]{3,}", re.sub(r"\b(?:монтаж|установка)\b", "", work["name"], flags=re.I)
        ):
            name = context.get("name") or table["row_names"].get(work["source_row"])
            if not name:
                continue
            work = {**work, "name": name, "original_name": work["name"], "work_name": name}
        result.append(work)
    return select_works(result, payload.get("query", ""))


def converted_page(path, number, signature):
    record = path / "docling" / f"page-{number}.json"
    if not record.is_file():
        return None
    result = json.loads(record.read_text(encoding="utf-8"))
    if not valid_record(result, signature):
        return None
    table = estimate_table(result)
    return {
        "text": result.get("analysis_text", result["text"]),
        "raw_text": result["text"],
        "layout": result.get("analysis_layout", result["layout"]),
        "confidence": result["confidence"],
        "table": table,
    }


def convert_document(path, signature, pages, report, batch_size=None):
    destination = path / "docling"
    complete = destination / "complete.json"
    cached = json.loads(complete.read_text(encoding="utf-8")) if complete.exists() else {}
    if cached.get("source") == signature and cached.get("engine") == ENGINE:
        report({"done": pages, "total": pages, "page": pages})
        return True
    complete.unlink(missing_ok=True)
    (destination / "progress.json").unlink(missing_ok=True)
    pending = []
    for number in range(pages, 0, -1):
        record = destination / f"page-{number}.json"
        value = json.loads(record.read_text(encoding="utf-8")) if record.exists() else {}
        if not valid_record(value, signature):
            pending.append(number)
    converted = pages - len(pending)
    executable = Path(os.getenv("DOCUMENT_DOCLING_PYTHON", ".runtime/docling-venv/bin/python"))
    if not executable.is_file():
        raise ValueError(
            "Преобразователь Docling не установлен. Файл сохранён; повторите обработку после настройки сервера."
        )
    previous = None

    def tick():
        nonlocal previous
        progress = destination / "progress.json"
        if progress.exists():
            value = json.loads(progress.read_text(encoding="utf-8"))
            if value != previous:
                report({**value, "done": min(pages, converted + value["done"]), "total": pages})
                previous = value

    report({"done": converted, "total": pages, "page": pending[0] if pending else pages})
    try:
        run(
            [
                str(executable.absolute()),
                str(Path(__file__).with_name("docling_runner.py")),
                str(path / "source.pdf"),
                str(destination),
                "--signature",
                signature,
                *(
                    ["--pages", *(str(number) for number in pending[:batch_size])]
                    if batch_size and pending
                    else []
                ),
            ],
            timeout=pages * 240 + 120,
            check=True,
            capture_output=True,
            on_tick=tick,
        )
    except subprocess.SubprocessError as error:
        raise ValueError(
            "Docling остановился при преобразовании. Уже прочитанные страницы сохранены; повторите обработку."
        ) from error
    tick()
    if not complete.exists() and not batch_size:
        raise ValueError("Docling не завершил преобразование. Повторите обработку файла.")
    return complete.exists()
