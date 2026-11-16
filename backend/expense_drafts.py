import re
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from . import matcher

MAX_LINES = 20
PROMPT = Path(__file__).with_name("prompts") / "expense_drafts.md"
NUMBER = r"\d+(?:[.,]\d+)?"
UNIT = r"шт\.?|л|литр(?:а|ов)?|ч|час(?:а|ов)?|км|кг|м²|м2|м|дн\.?|рейс(?:а|ов)?|услуг[аи]?|компл\.?"
CURRENCY = r"(?:BYN|руб(?:\.|л(?:ь|я|ей))?|белорусск\w* рубл\w*|р\.)"
PRICE = re.compile(
    rf"(?:\bпо\s+(?P<rate>{NUMBER})(?:\s*{CURRENCY})?(?!\d|[.,]\d)|"
    rf"(?P<each>{NUMBER})\s*{CURRENCY}\s*(?:/\s*(?:{UNIT})|за\s+(?:единицу|{UNIT})))(?!\w)",
    re.IGNORECASE,
)
LINE = re.compile(
    rf"(?P<name>.+?)\s*[-:–—]?\s+(?P<quantity>{NUMBER})\s*(?P<unit>{UNIT})(?!\w)"
    rf"(?:\s*,?\s*(?P<price>{PRICE.pattern}))?\s*\.?$",
    re.IGNORECASE,
)
TOTAL = re.compile(r"\b(?:за\s+вс[её]|всего|итого)\b", re.IGNORECASE)
SPOKEN = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    **dict(
        zip(
            [
                "десять",
                "одиннадцать",
                "двенадцать",
                "тринадцать",
                "четырнадцать",
                "пятнадцать",
                "шестнадцать",
                "семнадцать",
                "восемнадцать",
                "девятнадцать",
            ],
            range(10, 20),
            strict=True,
        )
    ),
    **dict(
        zip(
            [
                "двадцать",
                "тридцать",
                "сорок",
                "пятьдесят",
                "шестьдесят",
                "семьдесят",
                "восемьдесят",
                "девяносто",
            ],
            range(20, 100, 10),
            strict=True,
        )
    ),
    **dict(
        zip(
            [
                "сто",
                "двести",
                "триста",
                "четыреста",
                "пятьсот",
                "шестьсот",
                "семьсот",
                "восемьсот",
                "девятьсот",
            ],
            range(100, 1000, 100),
            strict=True,
        )
    ),
}
WORD_NUMBER = "(?:" + "|".join(SPOKEN) + ")"
SPOKEN_RUN = re.compile(rf"\b{WORD_NUMBER}(?:[ \t]+{WORD_NUMBER})*\b", re.IGNORECASE)
RUBLES_AND_KOPECKS = re.compile(
    r"(?P<rub>\d+)\s+рубл(?:ь|я|ей)\s+(?P<kop>\d{1,2})\s+копе(?:йка|йки|ек)\b",
    re.IGNORECASE,
)


class Draft(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    quantity: Decimal | None = Field(default=None, gt=0, le=1000000, decimal_places=4)
    rate: Decimal | None = Field(default=None, ge=0, le=1000000, decimal_places=4)
    quote: str = Field(min_length=1, max_length=600)


class ParsedDrafts(BaseModel):
    rows: list[Draft] = Field(min_length=1, max_length=MAX_LINES)


def decimal(value):
    return Decimal(value.replace(",", ".")) if value else None


def with_digits(text):
    def replace(match):
        values = [SPOKEN[word] for word in match.group().casefold().split()]
        if any(left <= right or (left < 20 and right < 10) for left, right in pairwise(values)):
            return match.group()
        return str(sum(values))

    text = SPOKEN_RUN.sub(replace, text)
    return RUBLES_AND_KOPECKS.sub(lambda match: f"{match['rub']}.{int(match['kop']):02d} BYN", text)


def local_draft(line):
    normalized = with_digits(line)
    match = LINE.fullmatch(normalized)
    if not match:
        partial = re.match(
            rf"(?P<name>.+?)\s+(?P<quantity>{NUMBER})\s*(?P<unit>{UNIT})(?!\w)",
            normalized,
            re.IGNORECASE,
        )
        if partial:
            return Draft(
                name=partial["name"].strip(" -:–—") or line[:300],
                unit=partial["unit"],
                quantity=decimal(partial["quantity"]),
                quote=line,
            )
        return Draft(name=line[:300], quote=line)
    return Draft(
        name=match["name"].strip(" -:–—") or line[:300],
        unit=match["unit"],
        quantity=decimal(match["quantity"]),
        rate=decimal(match["rate"] or match["each"]),
        quote=line,
    )


async def parse_expenses(text, settings):
    clauses = [line.strip(" \t•–—") for line in re.split(r"[;\n]+", text) if line.strip(" \t•–—")]
    if not clauses or len(clauses) > MAX_LINES or any(len(line) > 600 for line in clauses):
        raise ValueError("Укажите до 20 работ, каждую с новой строки")
    if matcher.provider(settings)["key"]:
        try:
            reply = await matcher.complete(PROMPT.read_text(encoding="utf-8"), text, settings)
            parsed = ParsedDrafts.model_validate(reply)
            quotes = [row.quote.strip() for row in parsed.rows]
            if not all(quote and quote in text for quote in quotes) or not all(
                any(quote in line or line in quote for quote in quotes) for line in clauses
            ):
                raise ValueError("Missing text evidence")
            for row in parsed.rows:
                normalized = with_digits(row.quote)
                prices = list(PRICE.finditer(normalized))
                price = prices[0] if len(prices) == 1 else None
                quantity_source = normalized[: price.start()] if price else normalized
                numbers = {decimal(value) for value in re.findall(NUMBER, quantity_source)}
                if row.quantity not in numbers:
                    row.quantity = None
                if (
                    not price
                    or row.rate != decimal(price["rate"] or price["each"])
                    or TOTAL.search(normalized)
                ):
                    row.rate = None
            return parsed.rows
        except (
            httpx.HTTPError,
            ValidationError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
        ):
            pass
    rows = []
    for line in clauses:
        try:
            rows.append(local_draft(line))
        except ValidationError:
            rows.append(Draft(name=line[:300], quote=line))
    return rows
