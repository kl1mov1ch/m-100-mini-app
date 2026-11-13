import json
import os
import subprocess
from pathlib import Path

from .docling_runner import ENGINE
from .execution import run


def converted_page(path, number, signature):
    record = path / "docling" / f"page-{number}.json"
    if not record.is_file():
        return None
    result = json.loads(record.read_text(encoding="utf-8"))
    if result.get("source") != signature or result.get("engine") != ENGINE:
        return None
    return {
        "text": result.get("analysis_text", result["text"]),
        "raw_text": result["text"],
        "layout": result.get("analysis_layout", result["layout"]),
        "confidence": result["confidence"],
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
        if value.get("source") != signature or value.get("engine") != ENGINE:
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
                report({**value, "done": converted + value["done"], "total": pages})
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
