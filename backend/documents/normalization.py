import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .aggregation import source_identity, source_summary, system_codes, work_key, work_label

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
    def evidence(sources):
        return frozenset(
            (source_identity(source), str(source.get("quantity")), source.get("unit"))
            for source in sources
        )

    prior_by_evidence = defaultdict(list)
    prior_by_source = defaultdict(set)
    previous = previous or []
    for index, row in enumerate(previous):
        source_set = evidence(row.get("sources", []))
        prior_by_evidence[source_set].append(index)
        for source in source_set:
            prior_by_source[source].add(index)
    grouped = defaultdict(list)
    for raw in works:
        work = normalise(raw)
        work["work_name"] = work_label(work["name"], work.get("work_name"))
        key = work_key(work["work_name"]) + "|" + canonical(work.get("unit"))
        grouped[key].append(work)
    result = []
    for key, items in grouped.items():
        ident = hashlib.sha256(key.encode()).hexdigest()[:24]
        all_notes = list(
            dict.fromkeys(
                work.get("notes", "").strip() for work in items if work.get("notes", "").strip()
            )
        )
        unique = {}
        for work in items:
            fingerprint = source_identity(work)
            if fingerprint in unique and unique[fingerprint]["quantity"] != work["quantity"]:
                unique[fingerprint] = {
                    **unique[fingerprint],
                    "quantity": None,
                    "evidence_warning": "Расходятся объёмы одной исходной строки",
                }
            else:
                unique.setdefault(fingerprint, work)
        items = list(unique.values())
        copies = []
        identities = {}
        for work in items:
            identity = (
                canonical(work.get("item_code")),
                canonical(work.get("quote")),
                work.get("quantity"),
                work.get("unit"),
                work.get("page_digest"),
            )
            if not identity[0] or not work.get("page_digest"):
                identity = (*identity, work.get("page"))
            if (
                identity[0]
                and identity in identities
                and work.get("page") != identities[identity].get("page")
            ):
                copies.append({**work, "duplicate_of_page": identities[identity]["page"]})
            else:
                identities.setdefault(identity, work)
        copied_locations = {source_identity(work) for work in copies}
        items = [work for work in items if source_identity(work) not in copied_locations]
        quote_pages = defaultdict(set)
        for work in items:
            quote_pages[canonical(work.get("quote"))].add(work.get("page"))
        duplicate = any(len(pages) > 1 for pages in quote_pages.values())
        tag_pages = defaultdict(set)
        unlocated = defaultdict(int)
        for work in items:
            for tag in system_codes(work.get("quote")):
                tag_pages[canonical(tag).replace(" ", ""), work["quantity"]].add(work.get("page"))
            if source_identity(work)[1] is None:
                unlocated[work.get("page"), work["quantity"]] += 1
        duplicate = (
            duplicate
            or any(len(pages) > 1 for pages in tag_pages.values())
            or any(count > 1 for count in unlocated.values())
        )
        missing = any(work["quantity"] is None or not work["unit"] for work in items)
        total = sum(
            (Decimal(str(work["quantity"])) for work in items if work["quantity"] is not None),
            Decimal(0),
        )
        row = {
            "id": ident,
            "name": items[0].get("work_name") or items[0]["name"],
            "category": items[0]["category"],
            "categories": list(
                dict.fromkeys(item.get("category") for item in items if item.get("category"))
            ),
            "section": items[0].get("section", "Без раздела"),
            "subsection": items[0].get("subsection", ""),
            "unit": items[0]["unit"],
            "quantity": None if missing or duplicate else str(total),
            "proposed_quantity": None if missing else str(total),
            "rate": None,
            "notes": "\n".join(all_notes)[:1900],
            "mention_count": len(items),
            "source_summary": source_summary(items),
            "quantity_mode": "sum",
            "sources": items,
            "duplicate_sources": copies,
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

        source_set = evidence(items)
        matching = prior_by_evidence[source_set]
        old = previous[matching[0]] if len(matching) == 1 else None
        if old and old.get("confirmed"):
            for field in (
                "quantity",
                "rate",
                "notes",
                "confirmed",
                "resolution",
                "issues",
                "amount",
                "quantity_mode",
                "category",
                "unit",
                "section",
                "subsection",
            ):
                if field in old:
                    row[field] = old[field]
            row["name"] = old["name"]
        else:
            overlapping = set().union(*(prior_by_source[source] for source in source_set))
            merged = [
                previous[index]
                for index in sorted(overlapping)
                if evidence(previous[index]["sources"]) <= source_set
            ]
            rates = {str(old["rate"]) for old in merged if old.get("rate") is not None}
            if len(rates) == 1:
                row["rate"] = next(iter(rates))
            earlier_reviews = [
                review for old in merged for review in old.get("previous_reviews", [])
            ]
            earlier_reviews.extend(
                {key: old.get(key) for key in ("name", "quantity", "unit", "rate", "notes")}
                for old in merged
                if old.get("confirmed")
            )
            if earlier_reviews:
                row["issues"].append(
                    "Объединены ранее проверенные позиции: подтвердите общий объём"
                )
                row["previous_reviews"] = earlier_reviews
        result.append(row)
    return sorted(result, key=lambda row: canonical(row["name"]))


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
