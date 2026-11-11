"""Bitrix Drive workbook adapter. Public link reads; REST webhook writes a new version."""

import base64
import hashlib
import io
import json
import math
import os
import re
from copy import copy
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
import openpyxl
from openpyxl.workbook.properties import CalcProperties

from .workbook_journal import is_journal

PUBLIC_URL = ""
READ_TIMEOUT = httpx.Timeout(25, connect=7)


def equal_quantities(left, right):
    return all(
        math.isclose(float(left.get(key, 0)), float(right.get(key, 0)), rel_tol=1e-10, abs_tol=1e-8)
        for key in set(left) | set(right)
    )


def validate_public(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "bitrix24public.com"
        or not re.fullmatch(r"/[a-zA-Z0-9.-]+/sheet/[a-zA-Z0-9]+/?", parsed.path)
    ):
        raise ValueError("Нужна публичная HTTPS-ссылка на таблицу bitrix24public.com")
    return url


async def read_with_fallback(operation):
    proxy = os.getenv("BITRIX_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL")
    try:
        return await operation(None)
    except httpx.HTTPStatusError as error:
        if (
            not proxy
            or error.response.status_code not in (403, 429)
            and error.response.status_code < 500
        ):
            raise
    except httpx.TransportError:
        if not proxy:
            raise
    return await operation(proxy)


async def fetch_public(url):
    validate_public(url)
    return await read_with_fallback(lambda proxy: fetch_public_workbook(url, proxy))


async def fetch_public_workbook(url, proxy):
    async with httpx.AsyncClient(
        timeout=READ_TIMEOUT, follow_redirects=True, proxy=proxy
    ) as client:
        page = await client.get(url)
        page.raise_for_status()
        config_match = re.search(r"editorJson:\s*(\{.*?\}),\s*\n", page.text)
        if not config_match:
            raise ValueError("Битрикс не предоставил документ. Проверьте доступ по ссылке.")
        config = json.loads(config_match[1])
        download = config["document"]["url"]
        host = urlparse(download).hostname
        portal = urlparse(url).path.split("/")[1]
        if host != portal:
            raise ValueError("Адрес файла не совпадает с порталом")
        public_download = re.search(r"linkToDownload:\s*'([^']+)'", page.text)
        content = None
        last_error = None
        urls = ([urljoin(url, public_download[1])] if public_download else []) + [download]
        for candidate in urls:
            try:
                r = await client.get(candidate)
                r.raise_for_status()
                if r.content.startswith(b"PK"):
                    content = r.content
                    break
            except httpx.HTTPError as error:
                last_error = error
        if content is None:
            if last_error is not None:
                raise last_error
            raise ValueError("Битрикс не предоставил скачиваемый Excel. Подключите вебхук Диска.")
        match = re.search(r'"object":\{"id":(\d+)', page.text)
        return content, {
            "name": config["document"]["title"],
            "file_id": int(match[1]) if match else None,
            "portal": portal,
        }


def read_workbook(content, mappings=None):
    if mappings:
        from .tables import extract

        return extract(content, mappings)
    w = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    result = {"positions": [], "entries": [], "sheet": None}
    for sheet in w:
        if is_journal(sheet):
            continue
        # Match by actual column headers, not the workbook's filename.
        header = next(
            (
                r
                for r in range(1, min(sheet.max_row, 15) + 1)
                if "наименован" in str(sheet.cell(r, 2).value).lower()
            ),
            None,
        )
        if not header:
            continue
        result["sheet"] = sheet.title
        section = "ОВ 3"
        dates = {}
        for r in range(header + 1, min(header + 5, sheet.max_row) + 1):
            for c in range(10, sheet.max_column + 1):
                value = sheet.cell(r, c).value
                if isinstance(value, datetime):
                    dates[c] = value.date().isoformat()
        for r in range(header + 1, sheet.max_row + 1):
            name = str(sheet.cell(r, 2).value or "").strip()
            if name.replace(" ", "") in ("ЭМ3", "ОВ3"):
                section = name
            unit, plan = sheet.cell(r, 3).value, sheet.cell(r, 4).value
            if not name or not unit or not isinstance(plan, (int, float)):
                continue
            ident = f"excel-{r}"
            p = {
                "id": ident,
                "name": name,
                "section": section,
                "unit": str(unit).lower().rstrip("."),
                "planned": plan,
                "rate": sheet.cell(r, 5).value or 0,
                "source_row": r,
            }
            result["positions"].append(p)
            for c, date in dates.items():
                quantity = sheet.cell(r, c).value
                if isinstance(quantity, (int, float)) and quantity:
                    result["entries"].append({"item_id": ident, "date": date, "quantity": quantity})
        break
    if not result["positions"]:
        raise ValueError(
            "Не найдена структура: наименование в B, единица в C, план в D. Нужна настройка соответствия столбцов."
        )
    return result


def patch_workbook(content, day, lines, catalogue, payroll=None, mappings=None, issues=None):
    from .workbook_calculation import recalculate

    if mappings:
        from .tables import patch

        return recalculate(
            patch(content, day, lines, catalogue, mappings),
            catalogue,
            mappings,
            issues,
        )
    book = openpyxl.load_workbook(io.BytesIO(content))
    info = read_workbook(content)
    sheet = book[info["sheet"]]
    current = {p["source_row"]: p for p in info["positions"]}
    if len(current) != len(catalogue):
        raise ValueError("Состав спецификации изменился. Обновите справочник перед отправкой.")
    for p in catalogue:
        if p["source_row"] not in current or any(
            current[p["source_row"]][key] != p[key] for key in ("name", "unit", "planned", "rate")
        ):
            raise ValueError("Структура таблицы изменилась. Обновите справочник перед отправкой.")
    day_obj = datetime.fromisoformat(day)
    date_row = next(
        (
            r
            for r in range(1, 8)
            if any(
                isinstance(sheet.cell(r, c).value, datetime)
                for c in range(10, sheet.max_column + 1)
            )
        ),
        3,
    )
    cols = [
        c
        for c in range(10, sheet.max_column + 1)
        if isinstance(sheet.cell(date_row, c).value, datetime)
        and sheet.cell(date_row, c).value.date() == day_obj.date()
    ]
    if len(cols) > 1:
        raise ValueError(
            "В таблице несколько столбцов с выбранной датой. Сначала устраните дубликат даты."
        )
    if cols:
        col = cols[0]
    else:
        existing = [
            c
            for c in range(10, sheet.max_column + 1)
            if isinstance(sheet.cell(date_row, c).value, datetime)
        ]
        col = max(existing, default=9) + 1
        # Do not overwrite non-date content in a prospective column.
        while any(sheet.cell(r, col).value is not None for r in range(1, sheet.max_row + 1)):
            col += 1
        from .workbook_calculation import extend_day_ranges

        extend_day_ranges(sheet, col, existing)
        for r in range(1, sheet.max_row + 1):
            src, dest = sheet.cell(r, max(10, col - 1)), sheet.cell(r, col)
            dest._style = copy(src._style)
        sheet.cell(date_row, col, day_obj).number_format = "dd.mm.yyyy"
        sheet.cell(date_row + 1, col, "объем")
    quantities = {line["item_id"]: line["quantity"] for line in lines}
    for p in catalogue:
        sheet.cell(p["source_row"], col).value = quantities.get(p["id"])
    book.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True)
    out = io.BytesIO()
    book.save(out)
    return recalculate(out.getvalue(), catalogue, issues=issues)


def validate_webhook(webhook):
    p = urlparse(webhook)
    if (
        p.scheme != "https"
        or not re.fullmatch(r"[a-z0-9-]+\.bitrix24\.(by|ru|com|kz|eu|de|net)", p.hostname or "")
        or not re.fullmatch(r"/rest/\d+/[A-Za-z0-9]+/?", p.path)
    ):
        raise ValueError("Укажите входящий HTTPS-вебхук вашего портала Битрикс24 с правом «Диск»")
    return webhook.rstrip("/") + "/"


async def rest(webhook, method, payload):
    base = validate_webhook(webhook)
    if method in ("disk.file.get", "disk.file.search"):
        return await read_with_fallback(lambda proxy: rest_request(base, method, payload, proxy))
    return await rest_request(base, method, payload, os.getenv("BITRIX_WRITE_PROXY_URL") or None)


async def rest_request(base, method, payload, proxy):
    timeout = (
        READ_TIMEOUT
        if method in ("disk.file.get", "disk.file.search")
        else httpx.Timeout(45, connect=7)
    )
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
        r = await client.post(base + method + ".json", json=payload)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise ValueError(
                "Битрикс: " + str(body["error"]) + " — " + str(body.get("error_description", ""))
            )
        return body["result"]


async def download_rest(webhook, file_id):
    meta = await rest(webhook, "disk.file.get", {"id": file_id})
    url = meta.get("DOWNLOAD_URL", "")
    if urlparse(url).scheme != "https" or urlparse(url).hostname != urlparse(webhook).hostname:
        raise ValueError("Битрикс вернул неподдерживаемый адрес скачивания")
    return await read_with_fallback(lambda proxy: download_workbook(url, meta, proxy))


async def download_workbook(url, meta, proxy):
    async with httpx.AsyncClient(
        timeout=READ_TIMEOUT, follow_redirects=True, proxy=proxy
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        if not r.content.startswith(b"PK"):
            raise ValueError("Не удалось скачать Excel с Диска")
        return r.content, meta


def workbook_identity(content):
    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    digest = hashlib.sha256()
    try:
        for sheet in book:
            if (sheet.max_row or 0) * (sheet.max_column or 0) > 3_000_000:
                raise ValueError("Не удалось проверить слишком большой файл Диска")
            digest.update(json.dumps(sheet.title, ensure_ascii=False).encode())
            for row_index, row in enumerate(sheet.values, 1):
                values = [(index, value) for index, value in enumerate(row, 1) if value is not None]
                if values:
                    digest.update(
                        json.dumps((row_index, values), ensure_ascii=False, default=str).encode()
                    )
        return digest.digest()
    finally:
        book.close()


async def resolve_public_file(public_url, webhook, existing_id=None):
    content, public = await fetch_public(public_url)
    public_id = public.get("file_id")
    if not webhook:
        return int(public_id) if public_id else None
    base = validate_webhook(webhook)
    portal = urlparse(public_url).path.split("/")[1].lower()
    if urlparse(base).hostname != portal:
        raise ValueError("Вебхук и публичная ссылка должны относиться к одному порталу")

    public_identity = None

    async def matches(ident):
        nonlocal public_identity
        try:
            candidate, meta = await download_rest(webhook, ident)
        except (httpx.HTTPError, ValueError, KeyError):
            return False
        if int(meta.get("ID") or ident) != ident:
            return False
        if hashlib.sha256(content).digest() == hashlib.sha256(candidate).digest():
            return True
        if public_identity is None:
            public_identity = workbook_identity(content)
        return public_identity == workbook_identity(candidate)

    candidates = {int(ident) for ident in (public_id, existing_id) if ident}
    for ident in candidates:
        if await matches(ident):
            return ident
    title = str(public.get("name", "")).strip()
    query = re.sub(r"\.xlsx?$", "", title, flags=re.I).strip()
    if len(query) < 3:
        raise ValueError("Публичная таблица не дала название для поиска на Диске")
    verified = set()
    for start in range(0, 200, 50):
        results = await rest(
            webhook, "disk.file.search", {"QUERY": query[:255], "TYPE": "file", "start": start}
        )
        for item in results:
            name = re.sub(r"\.xlsx?$", "", str(item.get("NAME", "")), flags=re.I)
            if name.strip().casefold() != query.casefold() or not item.get("ID"):
                continue
            ident = int(item["ID"])
            if ident not in candidates and await matches(ident):
                verified.add(ident)
            candidates.add(ident)
            if len(verified) > 1:
                raise ValueError(
                    "На Диске есть несколько одинаковых файлов. Опубликуйте нужную копию под отдельным названием."
                )
        if len(results) < 50:
            break
    if len(verified) == 1:
        return verified.pop()
    raise ValueError(
        "Не удалось подтвердить соответствие публичной таблицы файлу Диска. Проверьте доступ вебхука."
    )


async def upload_day(
    webhook,
    file_id,
    day,
    lines,
    catalogue,
    payroll=None,
    baseline=None,
    mappings=None,
    crew_by_day=None,
):
    from .workbook_journal import format_journal, verify_day_totals

    content, meta = await download_rest(webhook, file_id)
    if baseline is not None:
        remote = {}
        for e in read_workbook(content, mappings)["entries"]:
            if e["date"] == day:
                remote[e["item_id"]] = remote.get(e["item_id"], 0) + e["quantity"]
        wanted = {l["item_id"]: l["quantity"] for l in lines}
        if not equal_quantities(remote, baseline) and not equal_quantities(remote, wanted):
            raise ValueError(
                "Объёмы дня изменены в Битрикс. Обновите таблицу и проверьте изменения перед отправкой."
            )
    issues = []
    patched = patch_workbook(content, day, lines, catalogue, payroll, mappings, issues)
    entries = read_workbook(patched, mappings)["entries"]
    crew = dict(crew_by_day or {})
    if payroll:
        crew[day] = payroll["crew_count"]
    patched = format_journal(patched, catalogue, entries, crew, issues)
    if payroll:
        verify_day_totals(patched, day, payroll, len(catalogue))
    latest, _ = await download_rest(webhook, file_id)
    if hashlib.sha256(content).digest() != hashlib.sha256(latest).digest():
        raise ValueError(
            "Таблица изменена другим участником во время подготовки. Повторите синхронизацию."
        )
    result = await rest(
        webhook,
        "disk.file.uploadVersion",
        {
            "id": file_id,
            "fileContent": [meta["NAME"], base64.b64encode(patched).decode()],
        },
    )
    if not result:
        raise ValueError("Битрикс не подтвердил загрузку версии")
    verified, _ = await download_rest(webhook, file_id)
    from .workbook_calculation import verify_calculations

    verify_calculations(patched, verified)
    parsed = read_workbook(verified, mappings)
    actual = {}
    for e in parsed["entries"]:
        if e["date"] == day:
            actual[e["item_id"]] = actual.get(e["item_id"], 0) + e["quantity"]
    expected = {l["item_id"]: l["quantity"] for l in lines}
    if not equal_quantities(actual, expected):
        raise ValueError(
            "Версия отправлена, но проверка значений не прошла. Нажмите «Решить в приложении», чтобы прочитать актуальные данные и сравнить объёмы."
        )
    if payroll:
        verify_day_totals(verified, day, payroll, len(catalogue))
    return {
        "ok": True,
        "file_id": file_id,
        "issues": list({issue["id"]: issue for issue in issues}.values()),
    }


async def upload_journal(webhook, file_id, mappings, crew_by_day):
    from .workbook_calculation import verify_calculations
    from .workbook_journal import format_journal

    content, meta = await download_rest(webhook, file_id)
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    if any(is_journal(sheet) for sheet in book):
        return []
    parsed = read_workbook(content, mappings)
    issues = []
    patched = format_journal(content, parsed["positions"], parsed["entries"], crew_by_day, issues)
    latest, _ = await download_rest(webhook, file_id)
    if hashlib.sha256(content).digest() != hashlib.sha256(latest).digest():
        raise ValueError("Таблица обновилась во время оформления. Повторите чтение.")
    result = await rest(
        webhook,
        "disk.file.uploadVersion",
        {"id": file_id, "fileContent": [meta["NAME"], base64.b64encode(patched).decode()]},
    )
    if not result:
        raise ValueError("Битрикс24 не подтвердил создание листа «Журнал работ».")
    verified, _ = await download_rest(webhook, file_id)
    verified_book = openpyxl.load_workbook(io.BytesIO(verified), data_only=True)
    if not any(is_journal(sheet) for sheet in verified_book):
        raise ValueError("Лист «Журнал работ» пока не появился в Битрикс24.")
    verify_calculations(patched, verified)
    return issues
