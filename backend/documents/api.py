import io
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..analytics import style_sheet
from ..report_downloads import report_export
from .repository import DocumentJob, create, folder, owned, public, session

router = APIRouter(prefix="/api/documents")


@router.get("")
def list_jobs(request: Request):
    with session() as database:
        return [
            public(job)
            for job in database.scalars(
                select(DocumentJob)
                .where(DocumentJob.owner_id == request.state.user["telegram_id"])
                .order_by(DocumentJob.created_at.desc())
                .limit(40)
            )
        ]


@router.post("")
async def upload(request: Request):
    form = await request.form(max_files=1, max_fields=1, max_part_size=52 * 1024 * 1024)
    file = form.get("file")
    if not file or not hasattr(file, "read") or not str(file.filename).lower().endswith(".pdf"):
        raise HTTPException(422, "Выберите PDF-файл проекта")
    job = create(request.state.user["telegram_id"], Path(file.filename).name[:180])
    destination = folder(job.id)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        size = 0
        with (destination / "source.pdf").open("wb") as output:
            while block := await file.read(1024 * 1024):
                if size == 0 and not block.startswith(b"%PDF-"):
                    raise HTTPException(422, "Файл не является PDF")
                size += len(block)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(413, "Один PDF должен быть не больше 50 МБ")
                output.write(block)
        if not size:
            raise HTTPException(422, "Файл пустой")
        with session() as database:
            database.add(job)
            database.flush()
            return public(job)
    except Exception:
        shutil.rmtree(destination)
        raise
    finally:
        await file.close()


@router.get("/{ident}")
def get_job(ident: str, request: Request):
    with session() as database:
        return public(owned(database, ident, request.state.user["telegram_id"]))


class AnalysisInput(BaseModel):
    pages: list[int] = Field(default_factory=list, max_length=12)


@router.post("/{ident}/analyse")
def analyse(ident: str, request: Request, body: AnalysisInput):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if job.status not in {"text_ready", "draft", "needs_ai"}:
            raise HTTPException(409, "Дождитесь извлечения текста")
        available = {
            page["page"]
            for page in job.payload.get("page_results", [])
            if page["kind"] != "needs_ocr"
        }
        pages = sorted(set(body.pages))
        if not pages or not set(pages) <= available:
            raise HTTPException(422, "Выберите от 1 до 12 распознанных страниц")
        job.payload = {
            **job.payload,
            "selected_pages": pages,
            "notice": "Страницы поставлены в очередь ИИ",
        }
        job.status = "ai_queued"
        job.updated_at = datetime.now(UTC)
        return public(job)


@router.post("/{ident}/retry")
def retry(ident: str, request: Request):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if job.status not in {"needs_ocr", "failed"}:
            raise HTTPException(409, "Задание уже выполняется или завершено")
        job.status = "queued"
        job.updated_at = datetime.now(UTC)
        return public(job)


@router.get("/{ident}/export.xlsx")
def export(ident: str, request: Request, prepare: bool = False):
    def render(user):
        from openpyxl import Workbook

        with session() as database:
            job = owned(database, ident, user["telegram_id"])
            rows = job.payload.get("works", [])
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Работы по категориям"
            sheet.append(
                [
                    "№",
                    "Категория",
                    "Работа",
                    "Ед.",
                    "Объём",
                    "Расценка, BYN",
                    "Сумма, BYN",
                    "Примечания",
                    "Страница PDF",
                    "Что уточнить",
                ]
            )
            for index, work in enumerate(rows, 1):
                sheet.append(
                    [
                        index,
                        work["category"],
                        work["name"],
                        work["unit"],
                        work["quantity"],
                        None,
                        None,
                        work["notes"],
                        work["page"],
                        work["question"],
                    ]
                )
            style_sheet(sheet, 1, [7, 24, 55, 10, 14, 19, 19, 45, 16, 45], (6, 7))
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue()

    with session() as database:
        owned(database, ident, request.state.user["telegram_id"])
    return report_export(
        request.state.user,
        "Работы_из_PDF.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        render,
        prepare,
    )
