import base64
import io
import json
import re
from urllib.parse import urlparse

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from starlette.concurrency import run_in_threadpool

from . import bitrix, store

TEMPLATE_KEY = "bitrix_project_book"
REPORT_TARGET_KEY = "bitrix_report_webhook_id"
REPORT_FILE = "Журнал работ M-100.xlsx"
INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def book_name(value):
    name = re.sub(r"\.xlsx$", "", value.strip(), flags=re.I).strip(" .")
    if not name or INVALID_NAME.search(name):
        raise ValueError("Введите название Excel без символов / \\ : * ? и кавычек")
    if (name + ".xlsx").casefold() == REPORT_FILE.casefold():
        raise ValueError("Это название занято книгой отчётов. Введите название сметы.")
    return name + ".xlsx"


def starter_workbook(project_id):
    book = openpyxl.Workbook()
    book.properties.identifier = "M-100:" + project_id
    sheet = book.active
    sheet.title = "Смета"
    sheet.append(
        [
            "Наименование работы",
            "Единица измерения",
            "Плановый объём",
            "Расценка за единицу",
            "Раздел",
        ]
    )
    for cell, width in zip(sheet[1], (52, 21, 18, 23, 28), strict=True):
        sheet.column_dimensions[cell.column_letter].width = width
        cell.fill = PatternFill("solid", fgColor="21344A")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "B2"
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def public_file(meta, webhook):
    parsed = urlparse(meta.get("DETAIL_URL") or "")
    url = (
        parsed.geturl()
        if (
            parsed.scheme == "https"
            and parsed.netloc == urlparse(webhook).netloc
            and not parsed.query
            and not parsed.fragment
        )
        else ""
    )
    return {"id": int(meta["ID"]), "name": str(meta["NAME"]), "url": url}


async def personal_storage(webhook):
    owner = urlparse(webhook).path.split("/")[2]
    rows = await bitrix.rest(
        webhook, "disk.storage.getList", {"filter": {"ENTITY_TYPE": "user", "ENTITY_ID": owner}}
    )
    for row in rows or []:
        if row.get("ENTITY_TYPE") == "user" and str(row.get("ENTITY_ID")) == owner:
            return int(row["ID"])
    raise ValueError("У владельца вебхука нет личного Диска")


async def find_child(webhook, parent, name, kind):
    rows = await bitrix.rest(
        webhook, f"disk.{kind}.getChildren", {"id": parent, "filter": {"NAME": name}}
    )
    exact = [row for row in rows or [] if row.get("NAME") == name]
    if len(exact) > 1:
        raise ValueError("На Диске несколько файлов или папок с этим названием")
    return exact[0] if exact else None


async def object_folder(webhook, project):
    portal = urlparse(webhook)
    key = f"bitrix_disk_folder:{portal.hostname}:{portal.path.split('/')[2]}"
    with store.connect(project["db_path"]) as db:
        cached = store.setting(db, key)
    if cached:
        return int(cached)
    storage = await personal_storage(webhook)
    name = f"M-100 — {INVALID_NAME.sub(' ', project['name'])[:90].strip()} [{project['id'][:8]}]"
    row = await find_child(webhook, storage, name, "storage")
    if row and str(row.get("TYPE", "")).lower() != "folder":
        raise ValueError("На Диске уже есть файл с названием папки объекта")
    if not row:
        row = await bitrix.rest(
            webhook, "disk.storage.addFolder", {"id": storage, "data": {"NAME": name}}
        )
    ident = int(row["ID"])
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, key, str(ident))
    return ident


async def upload_new(webhook, folder, name, content):
    return await bitrix.rest(
        webhook,
        "disk.folder.uploadFile",
        {
            "id": folder,
            "data": {"NAME": name},
            "fileContent": [name, base64.b64encode(content).decode()],
            "generateUniqueName": False,
        },
    )


def saved_template(db):
    return json.loads(store.setting(db, TEMPLATE_KEY, "null"))


def workbook_belongs_to(content, project_id):
    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    try:
        return book.properties.identifier == "M-100:" + project_id
    finally:
        book.close()


def report_file_enabled(db):
    return bool(
        store.setting(db, REPORT_TARGET_KEY)
        and not (
            store.setting(db, "source") == "bitrix"
            and store.setting(db, "webhook")
            and store.setting(db, "file_id", "0") != "0"
        )
    )


def report_file(db, target):
    return json.loads(store.setting(db, f"bitrix_report_file:{target}", "null")) if target else None


async def sync_report_file(webhook, project, target, content):
    folder = await object_folder(webhook, project)
    host = urlparse(webhook).hostname
    with store.connect(project["db_path"]) as db:
        previous = report_file(db, target)
        pending_key = f"bitrix_report_pending:{target}"
        pending = json.loads(store.setting(db, pending_key, "null"))
    digest = (await run_in_threadpool(bitrix.workbook_identity, content)).hex()

    def remember_attempt():
        with store.connect(project["db_path"]) as db:
            store.set_setting(db, pending_key, json.dumps([host, folder, digest]))

    item = await find_child(webhook, folder, REPORT_FILE, "folder")
    if item:
        ident = int(item["ID"])
        existing, meta = await bitrix.download_rest(webhook, ident)
        remote_digest = (await run_in_threadpool(bitrix.workbook_identity, existing)).hex()
        if remote_digest != digest:
            known = previous and (
                previous["id"],
                previous["host"],
                previous["folder"],
                previous["digest"],
            ) == (ident, host, folder, remote_digest)
            if not known and pending != [host, folder, remote_digest]:
                raise ValueError(
                    "Журнал изменён на Диске. Переместите изменённый файл из папки объекта и повторите отправку."
                )
            remember_attempt()
            await bitrix.rest(
                webhook,
                "disk.file.uploadVersion",
                {
                    "id": ident,
                    "fileContent": [REPORT_FILE, base64.b64encode(content).decode()],
                },
            )
    else:
        remember_attempt()
        created = await upload_new(webhook, folder, REPORT_FILE, content)
        ident = int(created["ID"])
    verified, meta = await bitrix.download_rest(webhook, ident)
    if (await run_in_threadpool(bitrix.workbook_identity, verified)).hex() != digest:
        raise ValueError("Диск не подтвердил содержимое отчёта")
    result = public_file(meta, webhook)
    with store.connect(project["db_path"]) as db:
        store.set_setting(db, pending_key, "null")
        store.set_setting(
            db,
            f"bitrix_report_file:{target}",
            json.dumps(
                {
                    **result,
                    "host": host,
                    "folder": folder,
                    "digest": digest,
                },
                ensure_ascii=False,
            ),
        )
    return result
