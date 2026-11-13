import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import httpx
from dotenv import load_dotenv
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import case, or_, select

from .. import matcher, store, workspaces
from ..runtime import configure_runtime
from .execution import JobDeleted, cancellable, check_active, current_job, run
from .extraction import classify, propose
from .normalization import build_groups, financial_summary
from .page_cache import cache_page, cached_page, text_digest
from .progress import recover_interrupted, worker_lock
from .repository import DocumentJob, folder, session


def update(ident, **values):
    with session() as database:
        job = database.scalar(select(DocumentJob).where(DocumentJob.id == ident).with_for_update())
        if job is None:
            raise JobDeleted()
        progress = values.pop("progress", None)
        if "payload" in values:
            values["payload"] = {**values["payload"], "progress": job.payload.get("progress", {})}
        if progress is not None:
            job.payload = {
                **job.payload,
                "progress": {
                    "started_at": job.payload.get("progress", {}).get(
                        "started_at", datetime.now(UTC).isoformat()
                    ),
                    **progress,
                },
            }
        for key, value in values.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)


def phase(stage, page, **details):
    if ident := current_job.get():
        update(ident, progress={"stage": stage, "page": page, **details})


def ocr_page(source, number, destination):
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return None
    prefix = destination / f"page-{number}"
    image = prefix.with_suffix(".jpg")
    try:
        phase("rendering", number)
        run(
            [
                "pdftoppm",
                "-f",
                str(number),
                "-l",
                str(number),
                "-scale-to",
                "4000",
                "-singlefile",
                "-jpeg",
                "-gray",
                "-jpegopt",
                "quality=90",
                str(source),
                str(prefix),
            ],
            check=True,
            timeout=90,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        phase("ocr", number)
        result = run(
            ["tesseract", str(image), "stdout", "-l", "rus+eng", "tsv"],
            check=True,
            timeout=120,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        lines = {}
        confidence = []
        for word in csv.DictReader(
            io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            content = word.get("text", "").strip()
            if not content:
                continue
            key = (word["block_num"], word["par_num"], word["line_num"])
            lines.setdefault(key, []).append(
                {
                    "text": content,
                    "left": int(word["left"]),
                    "top": int(word["top"]),
                    "width": int(word["width"]),
                    "height": int(word["height"]),
                }
            )
            value = float(word.get("conf", -1))
            if value >= 0:
                confidence.append(value)
        text = ""
        layout = []
        for words in lines.values():
            if text:
                text += "\n"
            start = len(text)
            text += " ".join(word["text"] for word in words)
            layout.append(
                {
                    "start": start,
                    "end": len(text),
                    "left": min(word["left"] for word in words),
                    "top": min(word["top"] for word in words),
                    "right": max(word["left"] + word["width"] for word in words),
                    "bottom": max(word["top"] + word["height"] for word in words),
                }
            )
        page_row = next(
            csv.DictReader(io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE)
        )
        from .table_ocr import recognize

        phase("table_ocr", number)
        table = recognize(image)
        if table:
            separator = (
                "\nСправочный текст страницы (повтор тех же данных, не дополнительные объёмы):\n"
            )
            offset = len(table["text"]) + len(separator)
            table["layout"]["lines"].extend(
                {**line, "start": line["start"] + offset, "end": line["end"] + offset}
                for line in layout
            )
            table["text"] += separator + text
            return {**table, "confidence": sum(confidence) / len(confidence) if confidence else 0}
        return {
            "text": text,
            "layout": {
                "width": int(page_row["width"]),
                "height": int(page_row["height"]),
                "lines": layout,
            },
            "confidence": sum(confidence) / len(confidence) if confidence else 0,
        }
    except subprocess.SubprocessError:
        image.unlink(missing_ok=True)
        raise


def text_page(source, number):
    if not shutil.which("pdftotext"):
        return None
    result = run(
        ["pdftotext", "-f", str(number), "-l", str(number), "-bbox-layout", str(source), "-"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    root = ET.fromstring(result.stdout)
    page = next((item for item in root.iter() if item.tag.endswith("}page")), None)
    if page is None:
        return None
    text = ""
    layout = []
    for line in page.iter():
        if not line.tag.endswith("}line"):
            continue
        words = [word for word in line if word.tag.endswith("}word") and word.text]
        if not words:
            continue
        start = len(text)
        text += " ".join(word.text for word in words) + "\n"
        layout.append(
            {
                "start": start,
                "end": len(text),
                "left": float(line.attrib["xMin"]),
                "top": float(line.attrib["yMin"]),
                "right": float(line.attrib["xMax"]),
                "bottom": float(line.attrib["yMax"]),
            }
        )
    return {
        "text": text,
        "confidence": None,
        "layout": {
            "width": float(page.attrib["width"]),
            "height": float(page.attrib["height"]),
            "lines": layout,
        },
    }


def process(ident, payload):
    path = folder(ident)
    with PdfReader(path / "source.pdf") as reader:
        if reader.is_encrypted:
            raise ValueError("PDF защищён паролем. Загрузите открытую копию.")
        total = len(reader.pages)
        if not 1 <= total <= 2000:
            raise ValueError("Поддерживается от 1 до 2000 страниц. Разделите проект на тома.")
        results = list(payload.get("page_results", []))
        batch = 1 if not results else 3
        stop = min(total, len(results) + batch) if payload.get("automatic") else total
        update(ident, pages=total)
        for index in range(len(results), stop):
            check_active()
            phase("reading", index + 1)
            cached = cached_page(path, index + 1, payload.get("file_hash"))
            text = cached if cached else reader.pages[index].extract_text() or ""
            if isinstance(text, str) and len(text.strip()) >= 30:
                text = text_page(path / "source.pdf", index + 1) or text
            confidence = None
            layout = None
            if isinstance(text, str) and len(text.strip()) < 30:
                text = ocr_page(path / "source.pdf", index + 1, path)
                if text is None:
                    update(
                        ident,
                        status="needs_ocr",
                        payload={
                            **payload,
                            "page_results": results,
                            "notice": "Для сканированного PDF нужен OCR-обработчик с русским языком.",
                        },
                    )
                    return
            if isinstance(text, dict):
                confidence = text["confidence"]
                layout = text.get("layout")
                text = text["text"]
            if len(text) > 500000:
                raise ValueError(
                    f"Страница {index + 1} содержит слишком большой текстовый поток. Разделите PDF."
                )
            digest = text_digest(text)
            duplicate = next(
                (page["page"] for page in results if page.get("digest") == digest), None
            )
            cache_page(path, index + 1, text, confidence, layout, payload.get("file_hash"))
            results.append(
                {
                    "page": index + 1,
                    "kind": classify(text),
                    "characters": len(text),
                    "excerpt": text[:120],
                    "digest": digest,
                    "duplicate_of": duplicate,
                    "ocr_confidence": confidence,
                }
            )
            payload = {
                **payload,
                "page_results": results,
                "extraction_complete": len(results) == total,
            }
            update(ident, processed=index + 1, payload=payload)
    update(
        ident,
        status="ai_queued" if payload.get("automatic") else "text_ready",
        payload={**payload, "notice": "Страницы прочитаны. ИИ собирает найденные работы."},
    )


def chunks(text, limit=7000):
    start = 0
    header = ""
    if text.startswith("Таблица: ячейки по строкам и колонкам."):
        rows = re.findall(r"^Строка \d+: .+$", text, re.MULTILINE)
        header = (
            "Таблица: ячейки по строкам и колонкам. Повтор заголовков для привязки колонок.\n"
            + "\n".join(rows[:3])
            + "\n"
        )
        header = header[:2500]
    while start < len(text):
        context = header if start else ""
        available = limit - len(context)
        end = min(len(text), start + available)
        if end < len(text):
            boundary = text.rfind("\n", start + available // 2, end)
            if boundary > start:
                end = boundary
        yield context + text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - 250)


class BudgetExhausted(RuntimeError):
    pass


def extract_part(text, page, settings, query, depth=0, complete=None):
    try:
        return asyncio.run(propose(text, page, settings, query, complete=complete))
    except ValueError:
        if depth >= 3 or len(text) < 800:
            raise
        middle = text.rfind("\n", len(text) // 3, 2 * len(text) // 3)
        if middle < 1:
            middle = len(text) // 2
        first, questions_first = extract_part(
            text[:middle], page, settings, query, depth + 1, complete
        )
        second, questions_second = extract_part(
            text[middle:], page, settings, query, depth + 1, complete
        )
        return first + second, questions_first + questions_second


def analyse(ident, payload):
    settings = workspaces.shared()
    if not matcher.provider(settings)["key"]:
        update(
            ident,
            status="needs_ai",
            payload={
                **payload,
                "notice": "Подключите ИИ в настройках администратора. Файл сохранён.",
            },
        )
        return
    works = list(payload.get("works", []))
    questions = list(payload.get("questions", []))
    done = set(payload.get("analysed_chunks", []))
    pages = payload.get("selected_pages") or [
        page["page"] for page in payload.get("page_results", []) if not page.get("duplicate_of")
    ]
    ledger = []
    for page in pages:
        text = (folder(ident) / f"page-{page}.txt").read_text(encoding="utf-8")
        for index, part in enumerate(chunks(text)):
            ledger.append(
                (page, f"{page}:{index}:{hashlib.sha256(part.encode()).hexdigest()[:12]}", part)
            )
    payload = {**payload, "analysis_total": len(ledger)}
    update(ident, payload=payload)
    calls = int(payload.get("ai_calls", 0))
    budget = int(payload.get("call_budget", os.getenv("DOCUMENT_AI_CALL_LIMIT", "1000")))

    async def budgeted_complete(*args):
        nonlocal calls, payload
        if calls >= budget:
            raise BudgetExhausted()
        calls += 1
        payload = {**payload, "ai_calls": calls}
        update(ident, payload=payload)
        return await cancellable(matcher.complete(*args))

    for page, key, text in ledger:
        if key in done:
            continue
        phase("ai", page, chunk=len(done) + 1, chunks=len(ledger))
        try:
            suggested, clarifications = extract_part(
                text,
                page,
                settings,
                payload.get("query", "Подготовить перечень монтажных работ"),
                complete=budgeted_complete,
            )
        except BudgetExhausted:
            update(
                ident,
                status="needs_budget",
                payload={
                    **payload,
                    "notice": "Достигнут лимит обработки. Результат сохранён; подтвердите продолжение.",
                },
            )
            return
        works.extend(suggested)
        layout_path = folder(ident) / f"page-{page}.layout.json"
        if layout_path.is_file():
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            page_text = (folder(ident) / f"page-{page}.txt").read_text(encoding="utf-8")
            for work in suggested:
                start = page_text.find(work["quote"])
                if start >= 0:
                    work["highlights"] = [
                        {
                            "left": line["left"] / layout["width"] * 100,
                            "top": line["top"] / layout["height"] * 100,
                            "width": (line["right"] - line["left"]) / layout["width"] * 100,
                            "height": (line["bottom"] - line["top"]) / layout["height"] * 100,
                        }
                        for line in layout["lines"]
                        if line["end"] > start and line["start"] < start + len(work["quote"])
                    ]
        questions.extend(clarifications)
        done.add(key)
        groups = build_groups(works, payload.get("groups"))
        payload = {
            **payload,
            "works": works,
            "groups": groups,
            "summary": financial_summary(groups),
            "questions": list(dict.fromkeys(questions)),
            "analysed_chunks": sorted(done),
            "analysis_done": len(done),
            "ai_calls": calls,
        }
        update(ident, payload=payload)
    unresolved_pages = [
        page["page"] for page in payload.get("page_results", []) if page.get("kind") == "needs_ocr"
    ]
    drawings = [
        page["page"] for page in payload.get("page_results", []) if page.get("kind") == "drawing"
    ]
    with session() as database:
        total_pages = database.get(DocumentJob, ident)
        if total_pages is None:
            raise JobDeleted()
        total_pages = total_pages.pages
    complete_extraction = len(payload.get("page_results", [])) == total_pages
    coverage = {
        "pages": len(payload.get("page_results", [])),
        "analysed": len({page for page, key, _ in ledger if key in done}),
        "duplicates": sum(
            bool(page.get("duplicate_of")) for page in payload.get("page_results", [])
        ),
        "unreadable": unresolved_pages,
        "drawings": drawings,
        "complete": complete_extraction
        and all(key in done for _, key, _ in ledger)
        and {
            page["page"] for page in payload.get("page_results", []) if not page.get("duplicate_of")
        }
        <= {page for page, key, _ in ledger if key in done}
        and not unresolved_pages,
        "questions": len(questions),
        "low_ocr": [
            page["page"]
            for page in payload.get("page_results", [])
            if page.get("ocr_confidence") is not None and page["ocr_confidence"] < 75
        ],
    }
    update(
        ident,
        status="queued" if payload.get("automatic") and not complete_extraction else "needs_review",
        payload={
            **payload,
            "coverage": coverage,
            "notice": "Выборка собрана. Проверьте отмеченные строки и введите расценки. Геометрия чертежей автоматически не измерялась.",
        },
    )


def run_once():
    with session() as database:
        job = database.scalar(
            select(DocumentJob)
            .where(
                or_(
                    DocumentJob.status.in_(["queued", "ai_queued"]),
                    (DocumentJob.status.in_(["extracting", "analysing"]))
                    & (DocumentJob.updated_at < datetime.now(UTC) - timedelta(minutes=20)),
                )
            )
            .order_by(
                case((DocumentJob.status == "ai_queued", 0), else_=1),
                DocumentJob.updated_at,
                DocumentJob.created_at,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return False
        ident, payload, analysis = job.id, job.payload, job.status in {"ai_queued", "analysing"}
        job.status = "analysing" if analysis else "extracting"
        job.updated_at = datetime.now(UTC)
    context = current_job.set(ident)
    try:
        if analysis:
            analyse(ident, payload)
        else:
            process(ident, payload)
    except JobDeleted:
        shutil.rmtree(folder(ident), ignore_errors=True)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
        PdfReadError,
        httpx.HTTPError,
    ) as error:
        notice = (
            str(error)
            if isinstance(error, ValueError)
            else "Не удалось прочитать PDF. Проверьте файл и повторите загрузку."
        )
        with session() as database:
            job = database.get(DocumentJob, ident)
            if job is not None:
                job.status = "failed"
                job.payload = {**job.payload, "notice": notice}
                job.updated_at = datetime.now(UTC)
    finally:
        current_job.reset(context)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain", action="store_true")
    args = parser.parse_args()
    load_dotenv(store.ROOT / ".env")
    configure_runtime()
    lock = worker_lock()
    if lock is None:
        return
    with lock:
        recover_interrupted()
        while True:
            if not run_once():
                if args.drain:
                    return
                time.sleep(3)


if __name__ == "__main__":
    main()
