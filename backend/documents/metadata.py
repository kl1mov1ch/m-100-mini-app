from pypdf import PdfReader
from pypdf.errors import PdfReadError


def page_count(path):
    try:
        with PdfReader(path) as reader:
            if reader.is_encrypted:
                raise ValueError("PDF защищён паролем. Загрузите открытую копию.")
            pages = len(reader.pages)
            if not 1 <= pages <= 2000:
                raise ValueError("Поддерживается от 1 до 2000 страниц. Разделите проект на тома.")
            return pages
    except FileNotFoundError as error:
        raise ValueError("Исходный файл не найден. Загрузите PDF повторно.") from error
    except (PdfReadError, OSError, KeyError, TypeError) as error:
        raise ValueError("Не удалось открыть PDF. Загрузите исправный файл.") from error


import hashlib
import json
import time


def mark_uploaded(path, size, digest):
    temporary = path / "upload-complete.tmp"
    temporary.write_text(json.dumps({"bytes": size, "hash": digest}), encoding="utf-8")
    temporary.replace(path / "upload-complete.json")


def completed_upload(path):
    marker = path / "upload-complete.json"
    if not marker.exists() or time.time() - marker.stat().st_mtime < 5:
        return None
    try:
        result = json.loads(marker.read_text(encoding="utf-8"))
        source = path / "source.pdf"
        if source.stat().st_size != result["bytes"]:
            raise ValueError("Загрузка PDF не завершена. Загрузите файл повторно.")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != result["hash"]:
            raise ValueError("Файл PDF изменился при загрузке. Загрузите его повторно.")
        return result
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Загрузка PDF не завершена. Загрузите файл повторно.") from error
