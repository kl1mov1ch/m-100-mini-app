import asyncio
import io

import openpyxl

from backend import bitrix


def workbook(value):
    book = openpyxl.Workbook()
    book.active["A1"] = value
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_disk_search_verifies_document_contents(monkeypatch):
    expected = workbook("Инженерные сети")
    different = workbook("Другой объект")
    public_url = "https://bitrix24public.com" + "/demo.bitrix24.by/sheet/test"
    webhook = "https://demo.bitrix24.by/rest/1/test/"

    async def public(url):
        return expected, {"name": "Смета.xlsx", "file_id": None}

    async def rest(connection, method, payload):
        assert method == "disk.file.search" and payload["QUERY"] == "Смета"
        return [{"ID": "10", "NAME": "Смета.xlsx"}, {"ID": "20", "NAME": "Смета.xlsx"}]

    async def download(connection, ident):
        return (expected if ident == 20 else different), {"ID": ident}

    monkeypatch.setattr(bitrix, "fetch_public", public)
    monkeypatch.setattr(bitrix, "rest", rest)
    monkeypatch.setattr(bitrix, "download_rest", download)
    assert asyncio.run(bitrix.resolve_public_file(public_url, webhook)) == 20
