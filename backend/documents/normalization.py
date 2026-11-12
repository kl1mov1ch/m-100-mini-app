import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

UNIT_ALIASES = {
    "м": ("м", "1"),
    "мп": ("м", "1"),
    "погм": ("м", "1"),
    "пм": ("м", "1"),
    "метр": ("м", "1"),
    "метры": ("м", "1"),
    "мм": ("м", "0.001"),
    "см": ("м", "0.01"),
    "км": ("м", "1000"),
    "м2": ("м²", "1"),
    "квм": ("м²", "1"),
    "см2": ("м²", "0.0001"),
    "м3": ("м³", "1"),
    "кубм": ("м³", "1"),
    "л": ("м³", "0.001"),
    "шт": ("шт.", "1"),
    "штука": ("шт.", "1"),
    "штук": ("шт.", "1"),
    "ед": ("шт.", "1"),
    "кг": ("кг", "1"),
    "г": ("кг", "0.001"),
    "т": ("кг", "1000"),
    "компл": ("компл.", "1"),
    "комплект": ("компл.", "1"),
    "челч": ("чел·ч", "1"),
    "челчас": ("чел·ч", "1"),
    "челдн": ("чел·дн", "1"),
}


def canonical(value):
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    ).strip()


def unit_value(value):
    key = re.sub(r"[\s.\-/·\\]", "", canonical(value)).replace("²", "2").replace("³", "3")
    found = UNIT_ALIASES.get(key)
    return (found[0], Decimal(found[1])) if found else (str(value or "").strip(), None)


def decimal_value(value):
    try:
        number = Decimal(str(value).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and 0 <= number <= Decimal(1000000000) else None


def normalise(work):
    measure, factor = unit_value(work.get("unit"))
    quantity = decimal_value(work.get("quantity"))
    return {
        **work,
        "original_unit": work.get("unit"),
        "original_quantity": work.get("quantity"),
        "unit": measure or None,
        "quantity": str(quantity * factor) if quantity is not None and factor is not None else None,
        "conversion_factor": str(factor) if factor is not None else None,
    }


def build_groups(works, previous=None):
    prior = {row["id"]: row for row in previous or []}
    grouped = defaultdict(list)
    for raw in works:
        work = normalise(raw)
        key = "|".join(
            [
                canonical(work.get("category")),
                canonical(work.get("name")),
                canonical(work.get("unit")),
                canonical(work.get("notes")),
            ]
        )
        grouped[key].append(work)
    result = []
    for key, items in grouped.items():
        ident = hashlib.sha256(key.encode()).hexdigest()[:24]
        unique = {}
        for work in items:
            fingerprint = (work.get("page"), canonical(work.get("quote")), work.get("quantity"))
            unique.setdefault(fingerprint, work)
        items = list(unique.values())
        quote_pages = defaultdict(set)
        for work in items:
            quote_pages[canonical(work.get("quote"))].add(work.get("page"))
        duplicate = any(len(pages) > 1 for pages in quote_pages.values())
        if len(items) > 1:
            tags = [
                set(
                    re.findall(
                        r"(?<![\w])(?:П|В|ПВ|ВЕ|ПЕ|Т|К)\d+(?:[.]\d+)?(?![\w])",
                        work.get("quote", ""),
                        re.IGNORECASE,
                    )
                )
                for work in items
            ]
            duplicate = (
                duplicate
                or any(not value for value in tags)
                or any(
                    tags[left] & tags[right]
                    for left in range(len(tags))
                    for right in range(left + 1, len(tags))
                )
            )
        missing = any(work["quantity"] is None or not work["unit"] for work in items)
        total = sum(
            (Decimal(str(work["quantity"])) for work in items if work["quantity"] is not None),
            Decimal(0),
        )
        row = {
            "id": ident,
            "name": items[0]["name"],
            "category": items[0]["category"],
            "unit": items[0]["unit"],
            "quantity": None if missing or duplicate else str(total),
            "proposed_quantity": None if missing else str(total),
            "rate": None,
            "notes": items[0].get("notes", ""),
            "sources": items,
            "issues": (
                ["Возможный повтор: подтвердите, это те же работы или дополнительные"]
                if duplicate
                else []
            )
            + (["Не подтверждены объём или единица измерения"] if missing else [])
            + list(
                dict.fromkeys(
                    work["evidence_warning"] for work in items if work.get("evidence_warning")
                )
            ),
            "confirmed": False,
            "resolution": None,
        }
        old = prior.get(ident)
        if old and old.get("sources") == row["sources"]:
            for field in (
                "quantity",
                "rate",
                "notes",
                "confirmed",
                "resolution",
                "issues",
                "amount",
            ):
                if field in old:
                    row[field] = old[field]
        result.append(row)
    return sorted(result, key=lambda row: (row["category"], row["name"]))


def financial_summary(groups):
    priced = [
        row
        for row in groups
        if row.get("confirmed")
        and row.get("rate") is not None
        and row.get("quantity") is not None
        and not row.get("issues")
    ]
    amount = sum(
        (
            (Decimal(str(row["quantity"])) * Decimal(str(row["rate"]))).quantize(
                Decimal(".01"), rounding=ROUND_HALF_UP
            )
            for row in priced
        ),
        Decimal(0),
    ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    return {
        "positions": len(groups),
        "confirmed": sum(bool(row.get("confirmed")) for row in groups),
        "priced": len(priced),
        "amount": float(amount),
        "unresolved": sum(bool(row.get("issues")) for row in groups),
        "unpriced": sum(row.get("rate") is None for row in groups),
    }
