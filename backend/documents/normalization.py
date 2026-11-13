import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .aggregation import estimate_name, source_identity, source_summary, system_codes, work_key
from .geometry import perimeter
from .profile import load_template
from .work_catalogue import ventilation_type

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
    "сист": ("систем", "1"),
    "систем": ("систем", "1"),
    "система": ("систем", "1"),
    "системы": ("систем", "1"),
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
    original_unit = work.get("unit_cell") or work.get("unit")
    raw_unit = original_unit
    measure, factor = unit_value(original_unit)
    quantity = decimal_value(work.get("quantity"))
    standard = ventilation_type(work)
    cell = str(work.get("quantity_cell") or "").strip()
    if standard:
        definition = next(row for row in load_template()["works"] if row["id"] == standard[0])
        pair = definition.get("composite_units", {}).get(
            str(original_unit or "").replace(" ", "").casefold()
        )
        values = cell.replace(" ", "").split("/")
        if pair and len(pair) == len(values) and standard[2] in pair and "[OCR" not in cell:
            position = pair.index(standard[2])
            original_unit = pair[position]
            measure, factor = unit_value(original_unit)
            cell = values[position]
    compact_cell = re.sub(r"\s", "", cell)
    if cell and "[OCR" not in cell and re.fullmatch(r"\d+(?:[.,]\d+)?", compact_cell):
        quantity = decimal_value(compact_cell)
    elif cell:
        quantity = None
    if (
        standard
        and standard[2] == "шт."
        and re.fullmatch(r"w[iu]?m\.?", str(original_unit or ""), re.I)
    ):
        measure, factor = "шт.", Decimal(1)
    if (
        standard
        and standard[2] == "м²"
        and re.fullmatch(r"(?:2|2m|2м|м2|м²)", str(original_unit or "").casefold().strip())
    ):
        measure, factor = "м²", Decimal(1)
    if standard and standard[2] == "шт." and measure in {"шт.", "компл."}:
        measure = "шт."
    geometry_factor = None
    if standard and standard[0] == "duct" and measure == "м":
        geometry_factor = perimeter(work.get("dimensions"), work.get("dimension_text", ""))
        measure = "м²"
        if geometry_factor is None:
            quantity = None
        elif quantity is not None:
            quantity = (quantity * geometry_factor).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
    bundle = bool(standard and standard[0] == "consumables")
    if bundle:
        measure, factor, quantity = "компл.", Decimal(1), Decimal(1)
    evidence_warning = work.get("evidence_warning")
    if standard and not bundle and factor is not None and measure != standard[2]:
        evidence_warning = "Единица исходной строки отличается от единицы вида работ"
    if measure == "шт." and quantity is not None and quantity != quantity.to_integral_value():
        evidence_warning = "Дробное количество для штучной позиции: проверьте исходную ячейку"
    if work.get("classification_warning"):
        quantity = None
    if work.get("quantity_warning"):
        quantity = None
        evidence_warning = "Цифры в исходной ячейке требуют проверки по PDF"
    return {
        **work,
        **({"evidence_warning": evidence_warning} if evidence_warning else {}),
        "original_unit": raw_unit,
        "original_quantity": work.get("quantity_cell") or work.get("quantity"),
        "unit": measure or None,
        "quantity": str(quantity * factor) if quantity is not None and factor is not None else None,
        "conversion_factor": str(factor) if factor is not None else None,
        "bundle": bundle,
        "geometry_factor": str(geometry_factor) if geometry_factor is not None else None,
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
    prepared = []
    measures = defaultdict(set)
    for raw in works:
        work = normalise(raw)
        work["work_name"] = estimate_name(work)
        name_key = work_key(work["work_name"])
        if work.get("conversion_factor") is not None:
            measures[name_key].add(work["unit"])
        prepared.append((name_key, work))
    for name_key, work in prepared:
        measure = work.get("unit")
        if work.get("conversion_factor") is None and len(measures[name_key]) == 1:
            measure = next(iter(measures[name_key]))
        elif work.get("conversion_factor") is None:
            measure = None
        key = name_key + "|" + canonical(measure)
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
        # Identical specification wording on distinct pages is a legitimate
        # additional occurrence. Only unlocated quotes need a duplicate warning.
        duplicate = any(
            len(pages) > 1
            and any(
                work.get("source_row") is None
                for work in items
                if canonical(work.get("quote")) == quote
            )
            for quote, pages in quote_pages.items()
        )
        tag_pages = defaultdict(set)
        unlocated = defaultdict(int)
        for work in items:
            if work.get("source_row") is None:
                for tag in system_codes(work.get("quote")):
                    tag_pages[canonical(tag).replace(" ", ""), work["quantity"]].add(
                        work.get("page")
                    )
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
        bundle = all(work.get("bundle") for work in items)
        if bundle:
            total, missing, duplicate = Decimal(1), False, False
        row = {
            "id": ident,
            "name": items[0].get("work_name") or items[0]["name"],
            "category": items[0]["category"],
            "categories": list(
                dict.fromkeys(item.get("category") for item in items if item.get("category"))
            ),
            "section": items[0].get("section", "Без раздела"),
            "subsection": items[0].get("subsection", ""),
            "unit": next(
                (work["unit"] for work in items if work.get("conversion_factor") is not None),
                None,
            ),
            "quantity": None if missing or duplicate else str(total),
            "proposed_quantity": None if missing else str(total),
            "rate": None,
            "notes": "\n".join(all_notes)[:1900],
            "mention_count": len(items),
            "source_summary": source_summary(items),
            "quantity_mode": "manual" if bundle else "sum",
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
                    work[field]
                    for work in items
                    for field in ("evidence_warning", "classification_warning")
                    if work.get(field)
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
