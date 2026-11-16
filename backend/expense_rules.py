import re

EXTRA_SECTION = re.compile(
    r"^(?:доп\.?|дополнительные\s+(?:работы|расходы|затраты)|прочие\s+расходы)(?:$|\s*[·:–—])",
    re.IGNORECASE,
)
INCIDENTAL = re.compile(
    r"^(?:топливо|гсм|бензин|дизтопливо|дизельное\s+топливо|горюче-смазочные\s+материалы"
    r"|аренда|доставка|выезд\s+транспорта|оплата\s+(?:проезда|доставки))(?:\b|$)",
    re.IGNORECASE,
)


def extra_position(row):
    return any(
        EXTRA_SECTION.match(str(row.get(key) or "").strip()) for key in ("section", "subsection")
    ) or bool(INCIDENTAL.match(str(row.get("name") or "").strip()))
