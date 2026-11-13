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
    except (PdfReadError, OSError, KeyError, TypeError) as error:
        raise ValueError("Не удалось открыть PDF. Загрузите исправный файл.") from error
