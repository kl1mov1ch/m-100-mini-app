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
from .conversion import convert_document, converted_page, table_works
from .examples import confirmed_examples
from .execution import JobDeleted, cancellable, check_active, current_job, run
from .extraction import classify, propose
from .families import assign_work_names
from .normalization import financial_summary
from .page_cache import cache_page, cached_page, text_digest
from .progress import recover_interrupted, worker_lock
from .repository import DocumentJob, folder, session
from .selection import page_index


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
            ["tesseract", str(image), "stdout", "-l", "rus+eng", "--psm", "6", "tsv"],
            check=True,
            timeout=300,
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


def process_docling(ident, payload, path, total):
    def report(progress):
        nonlocal payload
        phase("converting", progress["page"])
        payload = {**payload, "conversion_done": progress["done"], "conversion_total": total}
        update(ident, pages=total, payload=payload)

    complete = convert_document(
        path,
        payload.get("file_hash", ""),
        total,
        report,
        batch_size=8 if payload.get("conversion_done") else 1,
    )
    results = list(payload.get("page_results", []))
    known = {row["page"] for row in results}
    selected = list(payload.get("selected_specifications", []))
    for number in range(1, total + 1):
        if number in known:
            continue
        record = converted_page(path, number, payload.get("file_hash", ""))
        if record is None:
            continue
        from .selection import classify_page

        raw_kind = classify_page(record.get("raw_text", record["text"]))
        # The full text is retained for the archive only. AI extraction receives
        # bounded table rows, including their column headers and source boxes.
        table = record.get("table")
        kind = "specification" if table else raw_kind
        if not table and kind == "specification":
            kind = "uncertain"
        digest = text_digest(record.get("raw_text", record["text"]))
        duplicate = (
            next(
                (
                    row["page"]
                    for row in results
                    if row.get("digest") == digest and row["kind"] == "specification"
                ),
                None,
            )
            if kind == "specification"
            else None
        )
        if kind == "specification":
            selected.append(number)
            cache_page(
                path,
                number,
                table["text"],
                record["confidence"],
                {**table["layout"], "row_names": table["row_names"]},
                payload.get("file_hash"),
            )
        results.append(
            {
                "page": number,
                "kind": kind if kind == "specification" else "excluded_" + kind,
                "digest": digest,
                "characters": len(record["text"]),
                "excerpt": record["text"][:120],
                "duplicate_of": duplicate,
                "ocr_confidence": record["confidence"] if kind == "specification" else None,
            }
        )
    questions = list(payload.get("questions", []))
    unknown = [row["page"] for row in results if row["kind"] == "excluded_uncertain"]
    if complete and unknown:
        questions.append(
            "Проверьте отбор: не определён тип страниц "
            + ", ".join(map(str, sorted(unknown)))
            + ". Они исключены из автоматической выборки."
        )
    payload = {
        **payload,
        "page_results": sorted(results, key=lambda row: row["page"]),
        "text_complete": complete,
        "selection_streaming": True,
        "selection_complete": complete,
        "extraction_complete": complete,
        "selected_specifications": sorted(selected),
        "page_index": [
            {"page": row["page"], "kind": row["kind"].removeprefix("excluded_")} for row in results
        ],
        "questions": list(dict.fromkeys(questions)),
    }
    from .profile import profile_version
    from .structured import candidates
    from .workbook import estimate_rows

    works, controls = candidates(path, payload)
    payload = {
        **payload,
        "works": works,
        "controls": controls,
        "structured_extraction": True,
        "profile_version": profile_version(),
    }
    groups = estimate_rows(payload)
    payload = {**payload, "groups": groups, "summary": financial_summary(groups)}
    update(
        ident,
        pages=total,
        processed=len(results),
        payload=payload,
        status="ai_queued" if complete else "queued",
    )


def process(ident, payload):
    path = folder(ident)
    with PdfReader(path / "source.pdf") as reader:
        if reader.is_encrypted:
            raise ValueError("PDF защищён паролем. Загрузите открытую копию.")
        total = len(reader.pages)
        if not 1 <= total <= 2000:
            raise ValueError("Поддерживается от 1 до 2000 страниц. Разделите проект на тома.")
        if payload.get("engine") == "docling":
            process_docling(ident, payload, path, total)
            return
        strict = payload.get("selection_policy", "specifications") == "specifications"
        if strict and not payload.get("selection_complete"):
            if any(row.get("confirmed") for row in payload.get("groups", [])):
                raise ValueError(
                    "Есть подтверждённые строки. Создайте новую выборку по спецификациям."
                )
            saved = payload.get("page_index", [])
            if (path / "selection.json").exists():
                saved = json.loads((path / "selection.json").read_text(encoding="utf-8"))

            def report(number, indexed):
                nonlocal payload
                phase("indexing", number)
                payload = {
                    **payload,
                    "page_index": indexed,
                    "index_done": len(indexed),
                    "index_total": total,
                }
                update(ident, pages=total, payload=payload)

            def native(number):
                if payload.get("engine") == "docling":
                    return converted_page(path, number, payload.get("file_hash", ""))
                cached = cached_page(path, number, payload.get("file_hash"))
                return cached or text_page(path / "source.pdf", number)

            indexed = page_index(path / "source.pdf", total, path, native, saved, report)
            uncertain = [row["page"] for row in indexed if row["kind"] == "uncertain"]
            selected = [row["page"] for row in indexed if row["kind"] == "specification"]
            payload = {
                **payload,
                "page_index": indexed,
                "selection_complete": True,
                "selection_policy": "specifications",
                "selected_specifications": selected,
                "page_results": [],
                "works": [],
                "groups": [],
                "analysed_chunks": [],
                "analysis_done": 0,
                "analysis_total": 0,
                "section_context": {},
                "questions": [
                    f"Проверьте отбор: не определён тип страниц {', '.join(map(str, uncertain))}. Они исключены из автоматической выборки."
                ]
                if uncertain
                else [],
                "summary": financial_summary([]),
            }
            update(ident, processed=0, payload=payload)
        results = list(payload.get("page_results", []))
        selected_pages = (
            set(payload.get("selected_specifications", [])) if strict else set(range(1, total + 1))
        )
        batch = 1 if not any(row["kind"] == "specification" for row in results) else 3
        extracted = 0
        update(ident, pages=total)
        for index in range(len(results), total):
            if payload.get("automatic") and extracted >= batch:
                break
            if index + 1 not in selected_pages:
                kind = next(
                    (
                        row["kind"]
                        for row in payload.get("page_index", [])
                        if row["page"] == index + 1
                    ),
                    "uncertain",
                )
                results.append(
                    {
                        "page": index + 1,
                        "kind": "excluded_" + kind,
                        "characters": 0,
                        "excerpt": "",
                        "digest": f"excluded-{index + 1}",
                        "duplicate_of": None,
                        "ocr_confidence": None,
                    }
                )
                payload = {**payload, "page_results": results}
                update(ident, processed=index + 1, payload=payload)
                continue
            extracted += 1
            check_active()
            phase("reading", index + 1)
            cached = (
                converted_page(path, index + 1, payload.get("file_hash", ""))
                if payload.get("engine") == "docling"
                else cached_page(path, index + 1, payload.get("file_hash"))
            )
            text = cached
            if text is None:
                native = text_page(path / "source.pdf", index + 1)
                if native is not None:
                    text = native if len(native["text"].strip()) >= 30 else ""
                else:
                    text = reader.pages[index].extract_text() or ""
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
                    "kind": "specification" if strict else classify(text),
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
    if (
        not payload.get("regroup_only")
        and not payload.get("selection_streaming")
        and payload.get("selection_policy", "specifications") != "all"
        and not payload.get("selection_complete")
    ):
        update(ident, status="queued")
        return
    if (
        not payload.get("regroup_only")
        and payload.get("selection_complete")
        and not payload.get("selected_specifications")
    ):
        update(
            ident,
            status="needs_review",
            payload={
                **payload,
                "notice": "Таблицы с объёмами не найдены уверенно. Автоматическая выборка пуста; проверьте исходный документ.",
                "coverage": {"complete": False, "questions": len(payload.get("questions", []))},
            },
        )
        return
    settings = workspaces.shared()
    with session() as database:
        owner = database.get(DocumentJob, ident)
        if owner is None:
            raise JobDeleted()
        owner = owner.owner_id
    settings = {**settings, "document_examples": confirmed_examples(owner)}
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
    from .intent import select_works

    works = select_works(payload.get("works", []), payload.get("query", ""))
    questions = list(payload.get("questions", []))
    done = set(payload.get("analysed_chunks", []))
    pages = payload.get("selected_pages") or [
        page["page"]
        for page in payload.get("page_results", [])
        if not page.get("duplicate_of") and not page["kind"].startswith("excluded_")
    ]
    ledger = []
    for page in (
        [] if payload.get("regroup_only") or payload.get("structured_extraction") else pages
    ):
        text = (folder(ident) / f"page-{page}.txt").read_text(encoding="utf-8")
        for index, part in enumerate(chunks(text)):
            ledger.append(
                (page, f"{page}:{index}:{hashlib.sha256(part.encode()).hexdigest()[:12]}", part)
            )
    type_total = (
        len({work["name"] for work in works})
        if payload.get("structured_extraction")
        else len(ledger)
    )
    payload = {**payload, "analysis_total": type_total}
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

    if payload.get("structured_extraction") and not payload.get("visual_complete"):
        from .visual import resolve

        def visual_report(count, total, current):
            nonlocal payload
            phase("verifying", 0, done=count, total=total)
            payload = {
                **payload,
                "works": current,
                "visual_done": count,
                "visual_total": total,
                "analysis_done": count,
                "analysis_total": total,
            }
            update(ident, payload=payload)

        try:
            works = asyncio.run(
                resolve(
                    folder(ident),
                    {**payload, "works": works},
                    settings,
                    budgeted_complete,
                    visual_report,
                )
            )
        except BudgetExhausted:
            update(
                ident,
                status="needs_budget",
                payload={
                    **payload,
                    "notice": "Проверенные ячейки сохранены. Продолжите обработку.",
                },
            )
            return
        type_total = len({work["name"] for work in works})
        payload = {
            **payload,
            "works": works,
            "visual_complete": True,
            "analysis_done": 0,
            "analysis_total": type_total,
        }
        update(ident, payload=payload)

    while (payload.get("engine") == "docling" or payload.get("regroup_only")) and any(
        not work.get("work_name") for work in works
    ):
        phase("grouping", 0)
        try:
            asyncio.run(assign_work_names(works, settings, budgeted_complete))
        except BudgetExhausted:
            update(
                ident,
                status="needs_budget",
                payload={
                    **payload,
                    "works": works,
                    "notice": "Группировка сохранена. Продолжите обработку.",
                },
            )
            return
        payload = {**payload, "works": works}
        if payload.get("structured_extraction"):
            remaining = len({work["name"] for work in works if not work.get("work_name")})
            payload = {**payload, "analysis_done": type_total - remaining}
        update(ident, payload=payload)
    if payload.get("regroup_only") or payload.get("structured_extraction"):
        from .workbook import estimate_rows

        groups = estimate_rows({**payload, "works": works})
        update(
            ident,
            status="needs_review",
            payload={
                **payload,
                "regroup_only": False,
                "works": works,
                "analysis_done": type_total
                if payload.get("structured_extraction")
                else payload.get("analysis_done", 0),
                "groups": groups,
                "summary": financial_summary(groups),
                "publication": None,
                "coverage": {
                    "complete": bool(payload.get("selection_complete")) and not questions,
                    "pages": len(payload.get("page_results", [])),
                    "analysed": len(payload.get("selected_specifications", [])),
                    "questions": len(questions),
                },
                "notice": "Выборка собрана по таблицам. Проверьте количество и расценки.",
            },
        )
        return
    for page, key, text in ledger:
        if key in done:
            continue
        phase("ai", page, chunk=len(done) + 1, chunks=len(ledger))
        page_layout = folder(ident) / f"page-{page}.layout.json"
        row_names = (
            json.loads(page_layout.read_text(encoding="utf-8")).get("row_names", {})
            if page_layout.is_file()
            else {}
        )
        part_rows = set(re.findall(r"^Строка (\d+):", text, re.M))
        try:
            suggested, clarifications = extract_part(
                text,
                page,
                {
                    **settings,
                    "document_row_names": {
                        row: name for row, name in row_names.items() if row in part_rows
                    },
                    "document_section": payload.get("section_context", {})
                    if page in {payload.get("section_page"), payload.get("section_page", -2) + 1}
                    else {},
                    "document_work_names": list(
                        dict.fromkeys(
                            work.get("work_name") for work in works if work.get("work_name")
                        )
                    )[:100],
                },
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
        page_digest = next(
            (row.get("digest") for row in payload.get("page_results", []) if row["page"] == page),
            None,
        )
        for item in suggested:
            item["page_digest"] = page_digest
        for item in suggested:
            if item.get("section") and item["section"] != "Без раздела":
                payload = {
                    **payload,
                    "section_context": {
                        "section": item["section"],
                        "subsection": item.get("subsection", ""),
                    },
                    "section_page": page,
                }
        layout_path = folder(ident) / f"page-{page}.layout.json"
        if layout_path.is_file():
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            page_text = (folder(ident) / f"page-{page}.txt").read_text(encoding="utf-8")
            expanded = []
            for work in suggested:
                if work.get("source_row") is not None:
                    prefix = f"Строка {work['source_row']}: "
                    starts = [
                        match.end()
                        for match in re.finditer(r"^" + re.escape(prefix), page_text, re.MULTILINE)
                        if page_text.startswith(work["quote"], match.end())
                    ]
                else:
                    starts = [
                        match.start() for match in re.finditer(re.escape(work["quote"]), page_text)
                    ]
                    # Without a table row number a repeated quote cannot locate a unique item.
                    if len(starts) > 1:
                        work["evidence_warning"] = (
                            "Цитата повторяется на странице. Уточните объём по выделенным строкам."
                        )
                        starts = starts[:1]
                for start in starts or [-1]:
                    work = {**work, "source_start": start if start >= 0 else None}
                    if start < 0:
                        expanded.append(work)
                        continue
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
                    expanded.append(work)
            suggested = expanded
        works.extend(suggested)
        questions.extend(clarifications)
        done.add(key)
        from .workbook import estimate_rows

        selected_works = (
            table_works(folder(ident), {**payload, "works": works})
            if payload.get("engine") == "docling"
            else works
        )
        groups = estimate_rows({**payload, "works": selected_works})
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
            page["page"]
            for page in payload.get("page_results", [])
            if not page.get("duplicate_of") and not page["kind"].startswith("excluded_")
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
            "notice": (
                f"Отобрано листов с данными: {len(payload.get('selected_specifications', []))}. Чертежи и общие данные исключены."
                if payload.get("selection_policy") == "specifications"
                else "Выборка собрана. Проверьте отмеченные строки и введите расценки."
            ),
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
        if isinstance(error, ValueError):
            notice = str(error)
        elif isinstance(error, subprocess.TimeoutExpired):
            notice = "Распознавание страницы заняло слишком долго. Файл и готовые страницы сохранены — продолжите обработку."
        elif isinstance(error, httpx.HTTPError):
            notice = "ИИ не ответил. Промежуточные данные сохранены — повторите обработку позже."
        else:
            notice = "Не удалось обработать страницу. Файл и промежуточные данные сохранены — повторите обработку."
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
