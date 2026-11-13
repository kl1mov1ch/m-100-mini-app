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
    from .intent import select_works
    from .table_context import document_rows

    tables = {}
    for cached in (path / "docling").glob("page-*.json"):
        record = json.loads(cached.read_text(encoding="utf-8"))
        number = int(cached.stem.removeprefix("page-"))
        tables[number] = (
            estimate_table(record) if record.get("source") == payload.get("file_hash") else None
        )
    contexts = document_rows(tables)
    result = []
    for work in payload.get("works", []):
        table = tables.get(work.get("page"))
        if not table or work.get("source_row") not in table["rows"]:
            continue
        context = contexts.get((work["page"], work["source_row"]), {})
        if context.get("role") == "commissioning" and not re.search(
            r"налад|пуск", payload.get("query", ""), re.I
        ):
            continue
        if context.get("component"):
            continue
        work = {
            **work,
            "category": context.get("category") or work.get("category"),
            "quantity_cell": context.get("quantity_cell"),
            "unit_cell": context.get("unit_cell"),
        }
        if context.get("role") == "insulation_schedule":
            work = {
                **work,
                "original_name": work.get("original_name") or work["name"],
                "name": "Тепловая изоляция матами",
                "work_name": work.get("work_name")
                if work["name"] == "Тепловая изоляция матами"
                else None,
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
