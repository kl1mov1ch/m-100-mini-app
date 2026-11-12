import asyncio
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

import httpx
from dotenv import load_dotenv
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import or_, select

from .. import matcher, store, workspaces
from ..runtime import configure_runtime
from .extraction import classify, propose
from .repository import DocumentJob, folder, session


def update(ident, **values):
    with session() as database:
        job = database.get(DocumentJob, ident)
        for key, value in values.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)


def ocr_page(source, number, destination):
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return None
    prefix = destination / f"ocr-{number}"
    image = prefix.with_suffix(".png")
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(number),
                "-l",
                str(number),
                "-scale-to",
                "2500",
                "-singlefile",
                "-png",
                str(source),
                str(prefix),
            ],
            check=True,
            timeout=90,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = subprocess.run(
            ["tesseract", str(image), "stdout", "-l", "rus+eng"],
            check=True,
            timeout=120,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout
    finally:
        image.unlink(missing_ok=True)


def process(ident, payload):
    path = folder(ident)
    reader = PdfReader(path / "source.pdf")
    if reader.is_encrypted:
        raise ValueError("PDF защищён паролем. Загрузите открытую копию.")
    total = len(reader.pages)
    if total > 2000:
        raise ValueError(
            "В одном задании поддерживается до 2000 страниц. Разделите проект на тома."
        )
    results = payload.get("page_results", [])
    update(ident, pages=total)
    for index in range(len(results), total):
        text = (reader.pages[index].extract_text() or "")[:30000]
        if len(text.strip()) < 30:
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
        (path / f"page-{index + 1}.txt").write_text(text, encoding="utf-8")
        results.append(
            {
                "page": index + 1,
                "kind": classify(text),
                "characters": len(text),
                "excerpt": text[:350],
            }
        )
        payload = {**payload, "page_results": results}
        update(ident, processed=index + 1, payload=payload)
    update(
        ident,
        status="text_ready",
        payload={**payload, "notice": "Текст извлечён. Выберите страницы для разбора ИИ."},
    )


def analyse(ident, payload):
    settings = workspaces.shared()
    if not matcher.provider(settings)["key"]:
        update(
            ident,
            status="needs_ai",
            payload={**payload, "notice": "Подключите ИИ в настройках администратора."},
        )
        return
    works = list(payload.get("works", []))
    questions = list(payload.get("questions", []))
    done = list(payload.get("analysed_pages", []))
    for page in payload.get("selected_pages", []):
        if page in done:
            continue
        text = (folder(ident) / f"page-{page}.txt").read_text(encoding="utf-8")
        suggested, clarifications = asyncio.run(propose(text, page, settings))
        works.extend(suggested)
        questions.extend(clarifications)
        done.append(page)
        payload = {
            **payload,
            "works": works,
            "questions": list(dict.fromkeys(questions)),
            "analysed_pages": done,
        }
        update(ident, payload=payload)
    update(
        ident,
        status="draft",
        payload={
            **payload,
            "notice": "Подготовлен черновик. Проверьте объёмы и примечания перед переносом в смету.",
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
            .order_by(DocumentJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return False
        ident, payload, analysis = job.id, job.payload, job.status in {"ai_queued", "analysing"}
        job.status = "analysing" if analysis else "extracting"
        job.updated_at = datetime.now(UTC)
    try:
        if analysis:
            analyse(ident, payload)
        else:
            process(ident, payload)
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
            job.status = "failed"
            job.payload = {**job.payload, "notice": notice}
            job.updated_at = datetime.now(UTC)
    return True


def main():
    load_dotenv(store.ROOT / ".env")
    configure_runtime()
    while True:
        if not run_once():
            time.sleep(3)


if __name__ == "__main__":
    main()
