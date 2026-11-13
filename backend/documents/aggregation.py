import re
from functools import lru_cache

import snowballstemmer


def system_codes(value):
    return list(
        dict.fromkeys(
            re.findall(
                r"(?<![\w])(?:ПВ|ПЕ|ВЕ|П|В|Т|К)\s*\d+(?:[.]\d+)?(?![\w])",
                str(value or ""),
                re.IGNORECASE,
            )
        )
    )


@lru_cache(maxsize=4096)
def work_key(name):
    value = str(name or "").casefold().replace("ё", "е")
    value = re.sub(r"(?<![\w])(?:пв|пе|ве|п|в|т|к)\s*\d+(?:[.]\d+)?(?![\w])", " ", value)
    words = re.findall(r"[а-яa-z]+|\d+(?:[.,]\d+)?|[Øø⌀]", value)
    stemmer = snowballstemmer.stemmer("russian")
    return " ".join(sorted(stemmer.stemWords(words)))


def work_traits(name):
    return set(
        re.findall(
            r"демонтаж|радиальн|канальн|осев|гибк|жестк|взрывозащ|противопожар|огнезащ|обратн|теплоизоляц|медн|полипропилен",
            str(name or "").casefold().replace("ё", "е"),
        )
    )


def work_label(name, candidate):
    value = name.casefold().replace("ё", "е")
    # Stable estimate lines for clear ventilation work descriptions. Everything
    # else retains its validated suggested name or its original description.
    if value.startswith(("монтаж ", "установка ")):
        traits = work_traits(name)
        if re.match(r"(?:монтаж|установка) (?:(?:гибк|жестк|стальн)\w* )?воздуховод\w*\b", value):
            if traits == {"гибк"}:
                return "Монтаж воздуховодов гибких"
            if not traits or traits == {"жестк"}:
                return "Монтаж воздуховодов"
        if re.match(
            r"(?:монтаж|установка) (?:(?:радиальн|канальн|осев)\w* )?вентилятор\w*\b", value
        ):
            if traits == {"радиальн"}:
                return "Монтаж вентиляторов (радиальных)"
            if traits and traits <= {"осев", "канальн"}:
                return "Монтаж вентиляторов (канальных, осевых)"
    candidate = str(candidate or "").strip()[:180]
    name_words = set(work_key(name).split())
    candidate_words = set(work_key(candidate).split())
    generic = {"монтаж", "установк", "демонтаж", "работ", "систем"}
    if (
        candidate
        and any(word.isalpha() and word not in generic for word in name_words & candidate_words)
        and work_traits(name) <= work_traits(candidate)
    ):
        return candidate
    return name


def source_identity(source):
    # Same extraction from overlapping AI chunks counts once. Distinct physical
    # rows with identical wording remain distinct mentions.
    location = source.get("source_start")
    row = source.get("source_row")
    if row is not None:
        return (source.get("page"), row, "row")
    if location is not None:
        return (source.get("page"), location, "offset")
    return (
        source.get("page"),
        None,
        re.sub(r"\s+", " ", str(source.get("quote", "")).casefold()).strip(),
    )


def source_summary(sources):
    entries = {}
    for source in sources:
        code = source.get("item_code") or ", ".join(system_codes(source.get("quote")))
        value = f"{code + ' · ' if code else ''}стр. {source['page']}"
        if source.get("source_row") is not None:
            value += f", строка {source['source_row']}"
        if source.get("quantity") is not None:
            value += f" — {source['quantity']} {source.get('unit') or ''}"
        entries[value] = None
    suffix = f"; ещё {len(entries) - 16} — в источниках" if len(entries) > 16 else ""
    return (f"Упоминаний: {len(sources)}. " + "; ".join(list(entries)[:16]) + suffix)[:1900]


def notes_with_sources(row):
    return "\n".join(
        filter(
            None,
            [row.get("notes"), row.get("source_summary") or source_summary(row.get("sources", []))],
        )
    )
