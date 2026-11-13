import hashlib
import io
import shutil
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import profile_webhooks
from ..analytics import style_sheet
from ..report_downloads import report_export
from .examples import remember
from .metadata import mark_uploaded, page_count
from .normalization import build_groups, canonical, financial_summary, unit_value
from .progress import notify_queue
from .repository import DocumentJob, create, folder, owned, public, session, version

router = APIRouter(prefix="/api/documents")


@router.get("/webhooks")
def document_webhooks(request: Request):
    return profile_webhooks.list_webhooks(request.state.user["telegram_id"])


class UploadReservation(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    query: str = Field(default="", max_length=2000)
    selection_policy: Literal["all", "specifications"] = "all"
    engine: Literal["legacy", "docling"] = "legacy"


@router.post("/reserve")
def reserve_upload(request: Request, body: UploadReservation):
    if not body.name.lower().endswith(".pdf"):
        raise HTTPException(422, "Выберите PDF-файл")
    job = create(request.state.user["telegram_id"], Path(body.name.replace("\\", "/")).name)
    job.status = "uploading"
    query = body.query.strip() or "Собрать все монтажные работы по проекту"
    job.payload = {
        **job.payload,
        "query": query,
        "query_key": canonical(query),
        "automatic": True,
        "groups": [],
        "reviews": [],
        "selection_policy": body.selection_policy,
        "engine": body.engine,
    }
    path = folder(job.id)
    path.mkdir(parents=True, exist_ok=False)
    try:
        with session() as database:
            database.add(job)
            database.flush()
            return public(job)
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)
        raise


@router.post("/{ident}/file")
async def upload_reserved(ident: str, request: Request, background: BackgroundTasks):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if job.status != "uploading":
            raise HTTPException(409, "Этот файл уже отправлен на обработку")
    form = await request.form(max_files=1, max_fields=0, max_part_size=52 * 1024 * 1024)
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        raise HTTPException(422, "Выберите PDF-файл")
    path = folder(ident)
    try:
        with session() as database:
            owned(database, ident, request.state.user["telegram_id"])
        digest = hashlib.sha256()
        size = 0
        with (path / "source.pdf").open("wb") as output:
            while block := await file.read(1024 * 1024):
                if size == 0 and not block.startswith(b"%PDF-"):
                    raise HTTPException(422, "Файл не является PDF")
                size += len(block)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(413, "Один PDF должен быть не больше 50 МБ")
                with session() as database:
                    owned(database, ident, request.state.user["telegram_id"])
                output.write(block)
                digest.update(block)
        if not size:
            raise HTTPException(422, "Файл пустой")
        mark_uploaded(path, size, digest.hexdigest())
        try:
            pages = await run_in_threadpool(page_count, path / "source.pdf")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with session() as database:
            job = database.scalar(
                select(DocumentJob)
                .where(
                    DocumentJob.id == ident,
                    DocumentJob.owner_id == request.state.user["telegram_id"],
                )
                .with_for_update()
            )
            if job is None:
                raise HTTPException(404, "Загрузка отменена")
            existing = database.scalar(
                select(DocumentJob)
                .where(
                    DocumentJob.owner_id == job.owner_id,
                    DocumentJob.id != ident,
                    DocumentJob.status.not_in(["failed", "uploading"]),
                    DocumentJob.payload["file_hash"].as_string() == digest.hexdigest(),
                    DocumentJob.payload["query_key"].as_string() == job.payload["query_key"],
                )
                .limit(1)
            )
            if existing:
                database.delete(job)
                shutil.rmtree(path, ignore_errors=True)
                background.add_task(notify_queue)
                return public(existing)
            job.payload = {**job.payload, "file_hash": digest.hexdigest(), "file_bytes": size}
            job.pages = pages
            job.status = "queued"
            job.updated_at = datetime.now(UTC)
            background.add_task(notify_queue)
            return public(job)
    except BaseException:
        with session() as database:
            job = database.get(DocumentJob, ident)
            if (
                job
                and job.owner_id == request.state.user["telegram_id"]
                and job.status == "uploading"
            ):
                database.delete(job)
        shutil.rmtree(path, ignore_errors=True)
        raise
    finally:
        await file.close()


@router.post("/{ident}/delete")
def delete_document(ident: str, request: Request):
    with session() as database:
        job = database.scalar(
            select(DocumentJob)
            .where(
                DocumentJob.id == ident, DocumentJob.owner_id == request.state.user["telegram_id"]
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Документ уже удалён или недоступен")
        if job.status == "publishing":
            raise HTTPException(409, "Дождитесь завершения записи в Битрикс24")
        database.delete(job)
    shutil.rmtree(folder(ident), ignore_errors=True)
    return {"deleted": True}


@router.get("")
def list_jobs(request: Request):
    with session() as database:
        columns = ("id", "name", "status", "pages", "processed", "created_at", "updated_at")
        rows = database.execute(
            select(
                *(getattr(DocumentJob, name) for name in columns),
                DocumentJob.payload["query"].as_string().label("query"),
                DocumentJob.payload["notice"].as_string().label("notice"),
                DocumentJob.payload["summary"].label("summary"),
                DocumentJob.payload["coverage"].label("coverage"),
                DocumentJob.payload["progress"].label("progress"),
                DocumentJob.payload["analysis_done"].label("analysis_done"),
                DocumentJob.payload["analysis_total"].label("analysis_total"),
                DocumentJob.payload["file_bytes"].label("file_bytes"),
            )
            .where(DocumentJob.owner_id == request.state.user["telegram_id"])
            .order_by(DocumentJob.created_at.desc())
            .limit(40)
        ).mappings()
        return [
            {
                **{
                    name: version(row[name]) if name.endswith("_at") else row[name]
                    for name in columns
                },
                "payload": {
                    name: row[name]
                    for name in (
                        "query",
                        "notice",
                        "summary",
                        "coverage",
                        "progress",
                        "analysis_done",
                        "analysis_total",
                        "file_bytes",
                    )
                    if row[name] is not None
                },
            }
            for row in rows
        ]


@router.post("")
async def upload(request: Request, background: BackgroundTasks):
    form = await request.form(max_files=1, max_fields=3, max_part_size=52 * 1024 * 1024)
    file = form.get("file")
    if not file or not hasattr(file, "read") or not str(file.filename).lower().endswith(".pdf"):
        raise HTTPException(422, "Выберите PDF-файл проекта")
    job = create(
        request.state.user["telegram_id"], Path(str(file.filename).replace("\\", "/")).name[:180]
    )
    query = str(form.get("query") or "Подготовить перечень монтажных работ по проекту").strip()
    if len(query) > 2000:
        raise HTTPException(422, "Сократите запрос до 2000 символов")
    job.payload = {
        **job.payload,
        "query": query,
        "automatic": True,
        "groups": [],
        "reviews": [],
        "selection_policy": "all",
    }
    destination = folder(job.id)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        size = 0
        digest = hashlib.sha256()
        with (destination / "source.pdf").open("wb") as output:
            while block := await file.read(1024 * 1024):
                if size == 0 and not block.startswith(b"%PDF-"):
                    raise HTTPException(422, "Файл не является PDF")
                size += len(block)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(413, "Один PDF должен быть не больше 50 МБ")
                output.write(block)
                digest.update(block)
        if not size:
            raise HTTPException(422, "Файл пустой")
        mark_uploaded(destination, size, digest.hexdigest())
        try:
            job.pages = await run_in_threadpool(page_count, destination / "source.pdf")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with session() as database:
            existing = database.scalar(
                select(DocumentJob)
                .where(
                    DocumentJob.owner_id == job.owner_id,
                    DocumentJob.payload["file_hash"].as_string() == digest.hexdigest(),
                    DocumentJob.payload["query_key"].as_string() == canonical(query),
                    DocumentJob.status != "failed",
                )
                .limit(1)
            )
            if existing:
                shutil.rmtree(destination)
                background.add_task(notify_queue)
                return public(existing)
            job.payload = {
                **job.payload,
                "file_hash": digest.hexdigest(),
                "query_key": canonical(query),
                "file_bytes": size,
            }
            database.add(job)
            database.flush()
            background.add_task(notify_queue)
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


class RebuildInput(BaseModel):
    version: str


@router.post("/{ident}/rebuild")
def rebuild(ident: str, body: RebuildInput, request: Request, background: BackgroundTasks):
    with session() as database:
        job = database.scalar(
            select(DocumentJob)
            .where(
                DocumentJob.id == ident, DocumentJob.owner_id == request.state.user["telegram_id"]
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Документ не найден")
        if job.status not in {
            "needs_review",
            "ready",
            "draft",
            "failed",
            "needs_ai",
            "needs_budget",
            "text_ready",
        }:
            raise HTTPException(409, "Дождитесь завершения текущей обработки")
        if version(job.updated_at) != body.version:
            raise HTTPException(409, "Данные обновились. Откройте выборку повторно.")
        learned = list(job.payload.get("learned_examples", []))
        learned.extend(
            {key: row.get(key) for key in ("name", "section", "subsection", "unit", "confirmed")}
            for row in job.payload.get("groups", [])
            if row.get("confirmed") and not row.get("issues")
        )
        remember(database, job.owner_id, job.payload.get("groups", []))
        payload = {
            key: value
            for key, value in job.payload.items()
            if key in {"file_hash", "file_bytes", "query", "query_key"}
        }
        job.payload = {
            **payload,
            "automatic": True,
            "selection_policy": "specifications",
            "engine": "docling",
            "groups": [],
            "works": [],
            "reviews": [],
            "learned_examples": learned,
            "page_results": [],
            "questions": [],
        }
        job.status = "queued"
        job.processed = 0
        job.updated_at = datetime.now(UTC)
        (folder(ident) / "selection.json").unlink(missing_ok=True)
        background.add_task(notify_queue)
        return public(job)


@router.get("/{ident}/pages/{page}/preview")
def preview_page(ident: str, page: int, request: Request):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if page < 1 or page > job.pages:
            raise HTTPException(404, "Страница не найдена")
    path = folder(ident) / f"page-{page}.jpg"
    if not path.is_file():
        path = folder(ident) / "docling" / f"page-{page}.jpg"
    if not path.is_file():
        raise HTTPException(404, "Для этой страницы доступны текстовые источники")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{ident}/marked.pdf")
def marked_pdf(ident: str, request: Request, prepare: bool = False):
    from .annotations import annotated_pdf

    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if not job.payload.get("groups"):
            raise HTTPException(409, "Дождитесь появления выборки")
        filename = "Размечено_" + Path(job.name).stem[:90] + ".pdf"

    def render(user):
        with session() as database:
            current = owned(database, ident, user["telegram_id"])
            groups = current.payload.get("groups", [])
            allowed = (
                set(current.payload.get("selected_specifications", []))
                if current.payload.get("selection_policy") == "specifications"
                else None
            )
        return annotated_pdf(folder(ident) / "source.pdf", groups, allowed)

    return report_export(request.state.user, filename, "application/pdf", render, prepare)


class AnalysisInput(BaseModel):
    pages: list[int] = Field(default_factory=list, max_length=12)


@router.post("/{ident}/analyse")
def analyse(ident: str, request: Request, body: AnalysisInput, background: BackgroundTasks):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if job.status not in {"text_ready", "draft", "needs_ai", "needs_budget", "needs_review"}:
            raise HTTPException(409, "Дождитесь извлечения текста")
        available = {
            page["page"]
            for page in job.payload.get("page_results", [])
            if page["kind"] != "needs_ocr" and not page["kind"].startswith("excluded_")
        }
        pages = sorted(set(body.pages)) if body.pages else sorted(available)
        if not pages or not set(pages) <= available:
            raise HTTPException(422, "Выберите от 1 до 12 распознанных страниц")
        job.payload = {
            **job.payload,
            "selected_pages": pages if body.pages else [],
            "call_budget": int(job.payload.get("call_budget", 1000)) + 1000
            if job.status == "needs_budget"
            else int(job.payload.get("call_budget", 1000)),
            "notice": "Страницы поставлены в очередь ИИ",
        }
        job.status = "ai_queued"
        job.updated_at = datetime.now(UTC)
        background.add_task(notify_queue)
        return public(job)


@router.post("/{ident}/retry")
def retry(ident: str, request: Request, background: BackgroundTasks):
    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if job.status not in {"needs_ocr", "failed"}:
            raise HTTPException(409, "Задание уже выполняется или завершено")
        job.status = "queued"
        job.updated_at = datetime.now(UTC)
        background.add_task(notify_queue)
        return public(job)


class ReviewValues(BaseModel):
    section: str | None = Field(default=None, max_length=160)
    subsection: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: Decimal = Field(ge=0, le=1000000000, decimal_places=8)
    rate: Decimal = Field(ge=0, le=1000000000, decimal_places=4)
    unit: str = Field(min_length=1, max_length=24)
    notes: str = Field(default="", max_length=2000)
    resolution: Literal["sum", "one", "manual"] | None = None
    acknowledge_scope: bool = False


class ReviewInput(ReviewValues):
    version: str = Field(min_length=1, max_length=80)


class BatchItem(ReviewValues):
    group_id: str = Field(min_length=24, max_length=24)


class BatchReview(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    items: list[BatchItem] = Field(min_length=1, max_length=100)
    acknowledge_scope: bool = False


def apply_review(row, body):
    measure, factor = unit_value(body.unit)
    if factor != 1:
        raise HTTPException(
            422, "Укажите объём в единых единицах: м, м², м³, шт., кг, компл., чел·ч или чел·дн"
        )
    if row.get("issues") and not body.resolution:
        raise HTTPException(422, "Подтвердите способ проверки спорного объёма")
    if body.quantity * body.rate > Decimal(1000000000000):
        raise HTTPException(422, "Стоимость позиции превышает допустимый диапазон")
    if body.resolution == "sum" and (
        row.get("proposed_quantity") is None
        or Decimal(str(row["proposed_quantity"])) != body.quantity
        or measure != row.get("unit")
    ):
        raise HTTPException(
            422, "Для суммы используйте рассчитанный объём или выберите ручное уточнение"
        )
    if body.resolution == "one" and (
        not row.get("sources")
        or row["sources"][0].get("quantity") is None
        or Decimal(str(row["sources"][0]["quantity"])) != body.quantity
        or measure != row.get("unit")
    ):
        raise HTTPException(
            422, "Для повтора используйте объём первого источника или выберите ручное уточнение"
        )
    before = {
        key: row.get(key)
        for key in (
            "name",
            "category",
            "section",
            "subsection",
            "quantity",
            "unit",
            "rate",
            "notes",
            "confirmed",
        )
    }
    if body.name is not None:
        row["name"] = body.name.strip()
        if not row["name"]:
            raise HTTPException(422, "Укажите название работы")
    if body.section is not None:
        row["section"] = body.section.strip() or "Без раздела"
    if body.subsection is not None:
        row["subsection"] = body.subsection.strip()
    if body.category is not None:
        row["category"] = body.category.strip()
        if not row["category"]:
            raise HTTPException(422, "Укажите категорию")
    row.update(
        quantity=str(body.quantity),
        rate=str(body.rate),
        unit=measure,
        notes=body.notes,
        confirmed=True,
        resolution=body.resolution or "manual",
        issues=[],
    )
    row["amount"] = float(
        (body.quantity * body.rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    )
    return before


def save_reviews(ident, request, expected_version, items, acknowledge_scope):
    if len({group_id for group_id, _ in items}) != len(items):
        raise HTTPException(422, "Одна позиция не может повторяться в подтверждении")
    with session() as database:
        job = database.scalar(
            select(DocumentJob)
            .where(
                DocumentJob.id == ident, DocumentJob.owner_id == request.state.user["telegram_id"]
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Документ не найден")
        if job.status not in {"needs_review", "ready", "draft"}:
            raise HTTPException(409, "Дождитесь окончания обработки")
        if version(job.updated_at) != expected_version:
            raise HTTPException(
                409, "Выборка обновилась. Обновите данные и повторите подтверждение."
            )
        groups = [dict(row) for row in job.payload.get("groups", [])]
        reviews = list(job.payload.get("reviews", []))
        for group_id, body in items:
            row = next((row for row in groups if row["id"] == group_id), None)
            if row is None:
                raise HTTPException(404, "Позиция не найдена")
            before = apply_review(row, body)
            reviews.append(
                {
                    "group_id": group_id,
                    "actor": request.state.user["telegram_id"],
                    "at": datetime.now(UTC).isoformat(),
                    "before": before,
                    "after": {key: row.get(key) for key in before},
                }
            )
        summary = financial_summary(groups)
        acknowledge = acknowledge_scope or job.payload.get("acknowledge_scope", False)
        coverage = job.payload.get("coverage", {})
        if Decimal(str(summary["amount"])) > Decimal(1000000000000):
            raise HTTPException(422, "Итог превышает допустимый диапазон")
        ready = (
            bool(groups)
            and summary["priced"] == len(groups)
            and coverage.get("complete")
            and (
                not (
                    coverage.get("drawings") or coverage.get("low_ocr") or coverage.get("questions")
                )
                or acknowledge
            )
        )
        job.payload = {
            **job.payload,
            "publication": None,
            "groups": groups,
            "summary": summary,
            "reviews": reviews,
            "acknowledge_scope": acknowledge,
        }
        job.status = "ready" if ready else "needs_review"
        remember(
            database,
            job.owner_id,
            [row for row in groups if row["id"] in {item[0] for item in items}],
        )
        job.updated_at = datetime.now(UTC)
        return public(job)


@router.post("/{ident}/groups/{group_id}")
def review_group(ident: str, group_id: str, request: Request, body: ReviewInput):
    return save_reviews(ident, request, body.version, [(group_id, body)], body.acknowledge_scope)


@router.post("/{ident}/review")
def review_batch(ident: str, request: Request, body: BatchReview):
    return save_reviews(
        ident,
        request,
        body.version,
        [(item.group_id, item) for item in body.items],
        body.acknowledge_scope,
    )


@router.get("/{ident}/export.xlsx")
def export(ident: str, request: Request, prepare: bool = False, final: bool = False):
    def render(user):
        from openpyxl import Workbook

        with session() as database:
            job = owned(database, ident, user["telegram_id"])
            if final and job.status not in {"ready", "published"}:
                raise HTTPException(
                    409, "Для итогового отчёта подтвердите все объёмы, расценки и полноту выборки"
                )
            rows = job.payload.get("groups") or build_groups(job.payload.get("works", []))
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
                    "Раздел",
                    "Подраздел",
                ]
            )
            for index, work in enumerate(rows, 1):
                sheet.append(
                    [
                        index,
                        work["category"],
                        work["name"],
                        work["unit"],
                        float(work["quantity"]) if work["quantity"] is not None else None,
                        float(work["rate"]) if work.get("rate") is not None else None,
                        work.get("amount") if work.get("confirmed") else None,
                        work["notes"],
                        ", ".join(str(source["page"]) for source in work.get("sources", [])),
                        "Подтверждено"
                        if work.get("confirmed")
                        else "; ".join(work.get("issues", []))
                        or "Проверьте объём и введите расценку",
                        work.get("section", "Без раздела"),
                        work.get("subsection", ""),
                    ]
                )
            style_sheet(sheet, 1, [7, 24, 55, 10, 14, 19, 19, 45, 16, 45, 30, 30], (6, 7))
            sheet.freeze_panes = "D2"
            sheet.append(
                [
                    None,
                    None,
                    "Итого подтверждено",
                    None,
                    None,
                    None,
                    financial_summary(rows)["amount"],
                ]
            )
            from openpyxl.styles import Font, PatternFill

            for cell in sheet[sheet.max_row]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="007AFF")
            sheet.cell(sheet.max_row, 7).number_format = "#,##0.00"
            sources = workbook.create_sheet("Источники")
            sources.append(["Позиция", "Страница", "Исходный объём", "Исходная единица", "Цитата"])
            for work in rows:
                for source in work.get("sources", []):
                    sources.append(
                        [
                            work["name"],
                            source["page"],
                            source.get("original_quantity", source.get("quantity")),
                            source.get("original_unit", source.get("unit")),
                            source["quote"],
                        ]
                    )
            style_sheet(sources, 1, [50, 14, 18, 18, 100])
            report = workbook.create_sheet("Контроль")
            report.append(["Показатель", "Значение"])
            report.append(["Запрос", job.payload.get("query", "")])
            report.append(["Файл", job.name])
            report.append(["Страниц", job.pages])
            report.append(["Обработано", job.processed])
            report.append(["Проверено строк", financial_summary(rows)["confirmed"]])
            report.append(
                ["Стоимость подтверждённых работ, BYN", financial_summary(rows)["amount"]]
            )
            report.append(["Статус", "Итоговый отчёт" if final else "Черновик"])
            for question in job.payload.get("questions", []):
                report.append(["Вопрос для проверки", question])
            report.append(
                [
                    "Ограничения",
                    "Геометрия по изображениям не измерялась. Процент ошибок 1% не подтверждён испытаниями.",
                ]
            )
            style_sheet(report, 1, [48, 105])
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue()

    with session() as database:
        job = owned(database, ident, request.state.user["telegram_id"])
        if final and job.status not in {"ready", "published"}:
            raise HTTPException(409, "Подтвердите объёмы и расценки перед итоговой выгрузкой")
    return report_export(
        request.state.user,
        f"Выборка_{Path(job.name).stem[:90]}_{datetime.now(UTC):%Y-%m-%d}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        render,
        prepare,
    )
