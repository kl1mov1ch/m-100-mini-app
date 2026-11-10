"""Bitrix Drive workbook adapter. Public link reads; REST webhook writes a new version."""

import base64
import hashlib
import io
import json
import re
from copy import copy
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
import openpyxl
from openpyxl.workbook.properties import CalcProperties

PUBLIC_URL = ""


def validate_public(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "bitrix24public.com"
        or not re.fullmatch(r"/[a-zA-Z0-9.-]+/sheet/[a-zA-Z0-9]+/?", parsed.path)
    ):
        raise ValueError("Нужна публичная HTTPS-ссылка на таблицу bitrix24public.com")
    return url


async def fetch_public(url):
    validate_public(url)
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
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
        urls = ([urljoin(url, public_download[1])] if public_download else []) + [download]
        for candidate in urls:
            try:
                r = await client.get(candidate)
                r.raise_for_status()
                if r.content.startswith(b"PK"):
                    content = r.content
                    break
            except httpx.HTTPError:
                continue
        if content is None:
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


def patch_workbook(content, day, lines, catalogue, payroll=None, mappings=None):
    if mappings:
        from .tables import patch

        return add_payroll(patch(content, day, lines, catalogue, mappings), day, payroll)
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
        if col > 104:
            raise ValueError("Дата выходит за диапазон формул J:CZ. Требуется расширение шаблона.")
        for r in range(1, sheet.max_row + 1):
            src, dest = sheet.cell(r, max(10, col - 1)), sheet.cell(r, col)
            dest._style = copy(src._style)
        sheet.cell(date_row, col, day_obj).number_format = "dd.mm.yyyy"
        sheet.cell(date_row + 1, col, "объем")
    quantities = {line["item_id"]: line["quantity"] for line in lines}
    for p in catalogue:
        sheet.cell(p["source_row"], col).value = quantities.get(p["id"])
    if payroll:
        payouts = (
            book["Расчёт бригады"]
            if "Расчёт бригады" in book.sheetnames
            else book.create_sheet("Расчёт бригады")
        )
        headers = [
            "Дата",
            "Работников",
            "Работы, BYN",
            "На человека, BYN",
            "Человек с +0,01 BYN",
            "Повышенная доля, BYN",
        ]
        for c, value in enumerate(headers, 1):
            payouts.cell(1, c, value)
        payout_row = next(
            (r for r in range(2, payouts.max_row + 1) if str(payouts.cell(r, 1).value)[:10] == day),
            payouts.max_row + 1,
        )
        for c, value in enumerate(
            [
                day,
                payroll["crew_count"],
                payroll["amount"],
                payroll["per_person"],
                payroll["extra_people"],
                payroll["extra_per_person"],
            ],
            1,
        ):
            payouts.cell(payout_row, c, value)
            if c in (3, 4, 6):
                payouts.cell(payout_row, c).number_format = "0.00"
        for c, width in {"A": 16, "B": 16, "C": 20, "D": 24, "E": 27, "F": 28}.items():
            payouts.column_dimensions[c].width = width
    book.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


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
    async with httpx.AsyncClient(timeout=45) as client:
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
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        if not r.content.startswith(b"PK"):
            raise ValueError("Не удалось скачать Excel с Диска")
        return r.content, meta


async def upload_day(
    webhook, file_id, day, lines, catalogue, payroll=None, baseline=None, mappings=None
):
    content, meta = await download_rest(webhook, file_id)
    if baseline is not None:
        remote = {}
        for e in read_workbook(content, mappings)["entries"]:
            if e["date"] == day:
                remote[e["item_id"]] = remote.get(e["item_id"], 0) + e["quantity"]
        wanted = {l["item_id"]: l["quantity"] for l in lines}
        if remote != baseline and remote != wanted:
            raise ValueError(
                "Объёмы дня изменены в Битрикс. Обновите таблицу и проверьте изменения перед отправкой."
            )
    patched = patch_workbook(content, day, lines, catalogue, payroll, mappings)
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
    parsed = read_workbook(verified, mappings)
    actual = {}
    for e in parsed["entries"]:
        if e["date"] == day:
            actual[e["item_id"]] = actual.get(e["item_id"], 0) + e["quantity"]
    expected = {l["item_id"]: l["quantity"] for l in lines}
    if actual != expected:
        raise ValueError(
            "Версия отправлена, но проверка значений не прошла. Откройте Битрикс и проверьте дату вручную."
        )
    if payroll:
        payouts = openpyxl.load_workbook(io.BytesIO(verified), data_only=True)["Расчёт бригады"]
        row = next((r for r in payouts.values if str(r[0])[:10] == day), None)
        if not row or list(row[1:6]) != [
            payroll["crew_count"],
            payroll["amount"],
            payroll["per_person"],
            payroll["extra_people"],
            payroll["extra_per_person"],
        ]:
            raise ValueError("Не подтверждён расчёт бригады в Битрикс. Повторите отправку.")
    return {"ok": True, "file_id": file_id}


def add_payroll(content, day, payroll):
    if not payroll:
        return content
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = (
        book["Расчёт бригады"]
        if "Расчёт бригады" in book.sheetnames
        else book.create_sheet("Расчёт бригады")
    )
    for c, value in enumerate(
        [
            "Дата",
            "Работников",
            "Работы, BYN",
            "На человека, BYN",
            "Человек с +0,01 BYN",
            "Повышенная доля, BYN",
        ],
        1,
    ):
        sheet.cell(1, c, value)
    r = next(
        (r for r in range(2, sheet.max_row + 1) if str(sheet.cell(r, 1).value)[:10] == day),
        sheet.max_row + 1,
    )
    for c, value in enumerate(
        [
            day,
            payroll["crew_count"],
            payroll["amount"],
            payroll["per_person"],
            payroll["extra_people"],
            payroll["extra_per_person"],
        ],
        1,
    ):
        sheet.cell(r, c, value)
        if c in (3, 4, 6):
            sheet.cell(r, c).number_format = "0.00"
    for c, width in {"A": 16, "B": 16, "C": 20, "D": 24, "E": 27, "F": 28}.items():
        sheet.column_dimensions[c].width = width
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
