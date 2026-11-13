import json
import math
import re

from .. import matcher
from .aggregation import work_label
from .intent import requested_categories
from .profile import load_prompt
from .work_catalogue import catalogue_prompt

CATEGORIES = [
    "Вентиляция",
    "Отопление",
    "Водоснабжение",
    "Канализация",
    "Кондиционирование",
    "Электроснабжение",
    "Автоматика",
    "Прочее",
]


def classify(text):
    value = text.casefold()
    if len(value.strip()) < 30:
        return "needs_ocr"
    if any(word in value for word in ("спецификация", "ведомость", "количество", "характеристика")):
        return "specification"
    if any(word in value for word in ("схема", "план на", "аксонометр", "разрез")):
        return "drawing"
    return "description"


async def propose(
    text, page, settings, query="Подготовить перечень монтажных работ", complete=None
):
    from .normalization import unit_value
    from .retrieval import relevant_examples

    complete = complete or matcher.complete
    settings = {**settings, "response_token_limit": 6000}
    context = settings.get("document_section", {})
    result = await complete(
        load_prompt("extract") + "\n" + load_prompt("template"),
        json.dumps(
            {
                "page": page,
                "text": text,
                "query": query,
                "categories": CATEGORIES,
                "section_context": context,
                "known": settings.get("document_work_names", []),
                "structural_template": catalogue_prompt(),
                "row_names": settings.get("document_row_names", {}),
                "examples": relevant_examples(
                    query + " " + text[:1500], settings.get("document_examples", [])
                ),
            },
            ensure_ascii=False,
        ),
        settings,
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("works", []), list)
        or len(result.get("works", [])) > 50
    ):
        raise ValueError("Фрагмент слишком большой для надёжного разбора")
    works = []
    rejected = []
    table_candidates = []
    for item in result.get("works", [])[:50]:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        quote = str(item.get("quote", "")).strip()
        name = str(item.get("name", "")).strip()
        source_row = item.get("source_row")
        structured_header = False
        located_row = None
        conflicting_cell = False
        if type(source_row) is int and "Таблица: ячейки по строкам и колонкам." in text:
            matching = re.findall(r"^Строка " + str(source_row) + r": (.+)$", text, re.MULTILINE)
            if len(matching) == 1:
                quote = matching[0]
                located_row = source_row
                column = str(item.get("quantity_column") or "").replace("-", "–")
                if re.fullmatch(r"C\d+–C\d+", column):
                    pattern = re.escape(column) + r"=([^|]+)"
                    selected = re.search(pattern, quote)
                    headers = [
                        re.search(pattern, row)
                        for row in re.findall(r"^Строка \d+: .+$", text, re.MULTILINE)[:3]
                    ]
                    header = next(
                        (
                            found[1].strip()
                            for found in headers
                            if found and re.search(r"[а-яА-Яa-zA-Z]", found[1])
                        ),
                        None,
                    )
                    if selected and header:
                        conflicting_cell = "[OCR расходится:" in selected[1]
                        item["quantity_cell"] = selected[1].strip().split(" [OCR расходится:")[0]
                        item["quantity_header"] = header
                        item["unit_evidence"] = header
                        structured_header = bool(
                            re.search(r"кол|об[ъь]ем|длин|площад|поверх|масса", header, re.I)
                        )
                        # Units come from this row's unit cell (or from the
                        # selected measure header), never from a model guess.
                        unit_column = next(
                            (
                                match[1]
                                for header_row in re.findall(r"^Строка \d+: .+$", text, re.M)[:3]
                                for match in re.finditer(r"(C\d+–C\d+)=([^|]+)", header_row)
                                if re.search(r"единиц|ед\.?\s*изм", match[2], re.I)
                            ),
                            None,
                        )
                        unit_cell = (
                            re.search(re.escape(unit_column) + r"=([^|]+)", quote)
                            if unit_column
                            else None
                        )
                        if unit_cell:
                            item["unit"] = unit_cell[1].strip()
                            item["unit_evidence"] = unit_cell[1].strip()
                        elif re.search(r"м[²³23]|\bм\b|\bкг\b|\bшт\.?", header, re.I):
                            item["unit"] = re.findall(
                                r"м[²³23]|\bм\b|\bкг\b|\bшт\.?", header, re.I
                            )[-1]
                        else:
                            item["unit"] = None
        if len(quote) > 1500:
            raise ValueError("Уменьшите фрагмент: источник позиции слишком длинный")
        if len(quote) < 8 or quote not in text or not re.search(r"[а-яА-Яa-zA-Z]{3,}", name):
            rejected.append(f"Страница {page}: часть предложенных данных не подтверждена цитатой")
            continue
        quantity = item.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or not math.isfinite(quantity)
            or quantity < 0
        ):
            quantity = None
        proposed_quantity = quantity
        if conflicting_cell:
            quantity = None
            proposed_quantity = None
            item["question"] = (
                "Разные результаты распознавания числовой ячейки. Проверьте выделенную строку PDF."
            )
        if quantity is not None:
            expected_unit, factor = unit_value(item.get("unit"))
            grounded = False
            pattern = r"(?<![\w.,])(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?\s*(?:м[²³23]?|мм|см|км|шт\.?|кг|т|л|м\.?п\.?|компл\.?)(?![\w])"
            for match in re.finditer(pattern, quote, re.IGNORECASE):
                number = re.match(r"[\d \u00a0.,]+", match.group()).group().strip()
                actual_unit = match.group()[
                    len(re.match(r"[\d \u00a0.,]+", match.group()).group()) :
                ].strip()
                actual, factor_actual = unit_value(actual_unit)
                if re.match(r"\s*/\s*(?:ч|час|с|сек)", quote[match.end() :], re.IGNORECASE):
                    continue
                prefix = quote[max(0, match.start() - 18) : match.start()]
                if re.search(r"(?:диаметр|[Øø⌀]|\bDN)\s*$", prefix, re.IGNORECASE):
                    continue
                try:
                    parsed = float(number.replace(" ", "").replace("\u00a0", "").replace(",", "."))
                except ValueError:
                    continue
                if (
                    abs(parsed - quantity) < 1e-8
                    and actual == expected_unit
                    and factor == factor_actual
                ):
                    grounded = True
            if not grounded:
                quantity = None
        table_evidence = False
        if quantity is None and proposed_quantity is not None:
            header = str(item.get("quantity_header") or "").strip()
            cell = str(item.get("quantity_cell") or "").strip()
            unit_evidence = str(item.get("unit_evidence") or "").strip()
            count_header = (
                bool(
                    re.search(
                        r"кол(?:ичество|[- ]?во|[.])|об[ъь]ем|длин|площад|поверх|масса",
                        header,
                        re.IGNORECASE,
                    )
                )
                and header in text
            )
            numeric_cell = bool(cell) and cell in quote
            try:
                cell_matches = (
                    abs(float(cell.replace(" ", "").replace(",", ".")) - proposed_quantity) < 1e-8
                )
            except ValueError:
                cell_matches = False
            count_unit = str(item.get("unit") or "").strip().rstrip(".") == "шт"
            if (
                (count_header or structured_header)
                and numeric_cell
                and cell_matches
                and (count_unit or (unit_evidence and unit_evidence in text))
            ):
                table_evidence = True
        query_value = query.casefold()
        requested = requested_categories(query_value)
        if requested and "кроме" not in query_value and item.get("category") not in requested:
            continue
        work_index = len(works)

        def heading(field):
            value = str(item.get(field) or context.get(field) or "").strip()[:160]
            normalized = re.sub(r"\s+", " ", value.casefold())
            available = re.sub(r"\s+", " ", text.casefold())
            return (
                value
                if normalized and (normalized in available or value == context.get(field))
                else ""
            )

        item_code = str(item.get("item_code") or "").strip()[:100]
        if item_code.casefold() not in quote.casefold():
            item_code = ""
        works.append(
            {
                "name": name[:300],
                "work_name": work_label(name[:300], item.get("work_name")),
                "category": item.get("category")
                if item.get("category") in CATEGORIES
                else "Прочее",
                "unit": str(item.get("unit") or "")[:24] or None,
                "quantity": quantity,
                "quote": quote,
                "page": page,
                "source_row": located_row,
                "section": heading("section") or "Без раздела",
                "subsection": heading("subsection"),
                "item_code": item_code,
                "notes": str(item.get("notes") or "")[:1000],
                "question": str(item.get("question") or "Подтвердите позицию и объём по проекту")[
                    :500
                ],
                "confirmed": False,
            }
        )
        if table_evidence:
            table_candidates.append(
                {
                    "index": work_index,
                    "quantity": proposed_quantity,
                    "unit": item.get("unit"),
                    "quote": quote,
                    "header": header,
                    "cell": cell,
                }
            )
    if table_candidates:
        verification = await complete(
            load_prompt("verify"),
            json.dumps(
                {"text": text, "query": query, "candidates": table_candidates, "all_works": works},
                ensure_ascii=False,
            ),
            settings,
        )
        if not isinstance(verification, dict):
            raise ValueError("ИИ не вернул проверку табличных количеств")
        missing_quotes = verification.get("missing_quotes")
        if isinstance(missing_quotes, list):
            rejected.extend(
                f"Страница {page}: проверьте возможную пропущенную строку: {quote[:180]}"
                for quote in missing_quotes
                if isinstance(quote, str) and len(quote) >= 8 and quote in text
            )
        accepted = (
            {value for value in verification.get("accepted", []) if type(value) is int}
            if isinstance(verification.get("accepted"), list)
            else set()
        )
        for candidate in table_candidates:
            if candidate["index"] in accepted and isinstance(candidate["index"], int):
                work = works[candidate["index"]]
                work["quantity"] = candidate["quantity"]
                work["evidence_warning"] = (
                    "Количество из таблицы проверено ИИ; подтвердите привязку к колонке"
                )
    return works, rejected + [
        str(question)[:500]
        for question in (result.get("questions") or [])[:10]
        if isinstance(question, str)
    ]
