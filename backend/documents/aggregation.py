import re
from functools import lru_cache

import snowballstemmer

VENTILATION_WORKS = (
    (r"дроссель[ -]?клапан", "Монтаж дроссель-клапанов"),
    (
        r"(?:клапан.*(?:противопожар|огнезадерж)|(?:противопожар|огнезадерж).*клапан)",
        "Монтаж противопожарных клапанов",
    ),
    (r"(?:клапан.*обратн|обратн.*клапан)", "Монтаж обратных клапанов"),
    (r"заслонк.*взрывозащ", "Монтаж взрывозащищённых заслонок"),
    (r"(?:шумоглушител|глушител)", "Монтаж шумоглушителей"),
    (r"диффузор.*(?:вихрев|\bдпу\b)|\bдпу\b.*диффузор", "Монтаж вихревых диффузоров"),
    (r"диффузор.*индустриальн", "Монтаж индустриальных диффузоров"),
    (r"диффузор", "Монтаж диффузоров"),
    (r"реш[её]тк.*нерегулируем", "Монтаж нерегулируемых решёток"),
    (r"реш[её]тк.*регулируем", "Монтаж регулируемых решёток"),
    (r"реш[её]тк", "Монтаж решёток"),
    (r"лючк.*питометр|порт.*(?:замер|отбор проб)", "Монтаж измерительных портов"),
    (r"дефлектор", "Монтаж дефлекторов"),
    (r"зонт", "Монтаж зонтов"),
    (r"(?:приточн|приточно[ -]вытяжн|вытяжн)\w* установ", "Монтаж приточно-вытяжных установок"),
    (r"фильтр\w* рамн", "Монтаж рамных фильтров"),
    (r"устройств\w* воздухоприемн|воздухоприемн\w* устройств", "Монтаж воздухоприёмных устройств"),
    (r"переход\b|перехода\b", "Монтаж переходов воздуховодов"),
    (r"быстрос[ъь]емн.*изоляц", "Монтаж быстросъёмной изоляции"),
    (r"(?:теплоизоляц|изоляц).*мат|мат.*теплоизоляц", "Тепловая изоляция матами"),
    (r"огнезащит", "Устройство огнезащитного покрытия"),
)


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
    # Accessories in a supplied set do not change the primary labour type.
    # A radial fan with a flexible connector is still a radial fan.
    primary = re.split(r"\b(?:[lL]\s*=|в\s+комплекте|6\s+комплекте)", str(name or ""), maxsplit=1)[
        0
    ]
    return set(
        re.findall(
            r"демонтаж|радиальн|канальн|осев|гибк|жестк|взрывозащ|противопожар|огнезащ|обратн|теплоизоляц|медн|полипропилен",
            primary.casefold().replace("ё", "е"),
        )
    )


def work_label(name, candidate):
    value = re.sub(r"\s+", " ", name.casefold().replace("ё", "е")).strip()
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
            if traits - {"взрывозащ"} == {"радиальн"}:
                return (
                    "Монтаж вентиляторов (радиальных, взрывозащищённых)"
                    if "взрывозащ" in traits
                    else "Монтаж вентиляторов (радиальных)"
                )
            if traits - {"взрывозащ"} and traits <= {"осев", "канальн", "взрывозащ"}:
                return (
                    "Монтаж вентиляторов (канальных, осевых, взрывозащищённых)"
                    if "взрывозащ" in traits
                    else "Монтаж вентиляторов (канальных, осевых)"
                )
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


def estimate_name(source):
    name = source["name"]
    candidate = source.get("work_name")
    if candidate and candidate != name:
        name = work_label(name, candidate)
    name = re.sub(r"^\s*\d+[.)]?\s+", "", name)
    # Only trim clearly identified equipment codes and technical suffixes.
    # Keep descriptive qualifiers, such as flange vs. threaded, in the name.
    code = str(source.get("item_code") or "").strip()
    if len(code) >= 3 and re.search(r"\d", code):
        name = re.sub(r"(?<!\w)" + re.escape(code) + r"(?!\w)", " ", name, flags=re.IGNORECASE)
    name = re.split(
        r"\s+(?:[lpn]\s*[=:]|№\s*\d|#\s*\d)",
        name,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    name = re.sub(r"\s+\d+(?:[.,]\d+)?(?:\s*[xх×]\s*\d+(?:[.,]\d+)?){1,2}\s*(?:мм)?\s*$", "", name)
    name = re.sub(
        r"\s*(?:[Øø⌀#]|\bDN\s*|\bД[Уу]\s*|\bдиаметр\w*\s*)\d+(?:[.,]\d+)?(?:\s*[xх×]\s*\d+(?:[.,]\d+)?)*\s*(?:мм)?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = " ".join(name.split()).strip(" ,.;–-")
    value = name.casefold().replace("ё", "е")
    if re.match(r"^(?:тепловая изоляц|теплоизоляц|изоляц).*воздуховод", value):
        return "Тепловая изоляция воздуховодов"
    if source.get("category") == "Вентиляция" and value.startswith(
        ("монтаж ", "установка ", "устройство ")
    ):
        subject = value.split(" ", 1)[1]
        if not subject.startswith(("узла", "креплен", "комплекта", "подключен")):
            for pattern, label in VENTILATION_WORKS:
                if re.match(pattern, subject):
                    return label + (
                        " (взрывозащищённые)"
                        if "взрывозащ" in subject and "взрывозащ" not in label
                        else ""
                    )
    return work_label(name, name)


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
        detail = str(source.get("name") or "").strip()[:160]
        value = f"{code + ' · ' if code else ''}стр. {source['page']}"
        if source.get("source_row") is not None:
            value += f", строка {source['source_row']}"
        if source.get("quantity") is not None:
            value += f" — {source['quantity']} {source.get('unit') or ''}"
        if detail:
            value += " · " + detail
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
