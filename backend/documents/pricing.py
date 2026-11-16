"""Read price references and join them to compatible PDF rows."""

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from .aggregation import source_identity, without_position_number
from .normalization import canonical, decimal_value, unit_value

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_GUIDE = ROOT / "docs/document-price-guide.md"


def guide_rows(path, heading):
    if not path.exists():
        return []
    _, marker, section = path.read_text(encoding="utf-8").partition(f"## {heading}\n")
    if not marker:
        return []
    lines = [line for line in section.split("\n## ", 1)[0].splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


def offers_by_specification(path=PUBLIC_GUIDE):
    result = defaultdict(list)
    for key, seller, price, url, phone, terms, checked in guide_rows(path, "Материалы"):
        value = decimal_value(price)
        if value is not None and value > 0 and urlsplit(url).scheme == "https":
            result[key].append((value, seller, url, phone, terms, checked))
    return {key: sorted(offers) for key, offers in result.items()}


def ventilation_contacts():
    return [
        (None, seller, url, phone, terms, checked)
        for seller, url, phone, terms, checked in guide_rows(
            PUBLIC_GUIDE, "Запрос цены на воздуховоды"
        )
        if urlsplit(url).scheme == "https"
    ]


def pipe_specification(source):
    name = canonical(
        source.get("source_description") or source.get("original_name") or source["name"]
    )
    code = source.get("item_code") or ""
    if not (
        all(term in name for term in ("водогазопроводн", "оцинкованн", "обыкновенн"))
        and re.search(r"3262\s*[-–]\s*75", code + " " + name)
    ):
        return None
    size = re.fullmatch(
        r"(?:[Øø⌀#Фф$]|[Дд][Уу]\s*)(15|25)", str(source.get("dimension_text") or "").strip()
    )
    if size:
        nominal = size[1]
        wall = {"15": "2,8", "25": "3,2"}[nominal]
        return f"ВГП-оц-3262-Ду{nominal}-{wall}", f"Ду {nominal} × {wall} мм · ГОСТ 3262-75"
    return None


def material_rows(rows):
    """Use physical purchase quantities, before conversion to labour units."""
    offers = offers_by_specification()
    contacts = ventilation_contacts()
    result = {}
    seen = set()
    for row in rows:
        for source in row.get("sources", []):
            role = source.get("table_role")
            if role in {"work", "commissioning", "insulation_schedule"}:
                continue
            name = without_position_number(str(source.get("name") or row["name"]))
            if re.match(
                r"^(?:монтаж|прокладк|установк[аи] (?!насосная)|окраск|нанесение|испытани|по грунт|антикорроз\w* покрытие|устройство (?:огнезащит|изоляц))",
                name,
                re.I,
            ):
                continue
            identity = (row["category"], source_identity(source))
            if identity in seen:
                continue
            seen.add(identity)
            pipe = pipe_specification(source)
            spec = str(source.get("item_code") or "")
            line = str(source.get("dimension_text") or "")
            line = re.sub(r"\b0\s*=\s*(0[,.]\d+\s*мм)", r"δ=\1", line, flags=re.I)
            if line and canonical(line) != canonical(
                source.get("original_name") or source.get("name")
            ):
                spec = " · ".join(filter(None, (spec, line)))
            if pipe:
                name, spec = "Труба ВГП оцинкованная обыкновенная", pipe[1]
            unit, factor = unit_value(source.get("original_unit") or source.get("unit_cell"))
            raw = source.get("original_quantity") or source.get("quantity_cell")
            quantity = decimal_value(raw) if not source.get("quantity_warning") else None
            key = (
                row["category"],
                canonical(name),
                canonical(spec),
                unit,
                pipe[0] if pipe else None,
            )
            published = offers.get(pipe[0], []) if pipe and unit == "м" else []
            if (
                not published
                and row["category"] == "Вентиляция"
                and re.search(r"воздуховод.*оцинкован|воздуховод.*тонколист", name, re.I)
            ):
                published = contacts[:1]
            item = result.setdefault(
                key,
                {
                    "category": row["category"],
                    "name": name,
                    "spec": spec,
                    "unit": unit,
                    "quantity": Decimal(0),
                    "pages": set(),
                    "offers": published,
                },
            )
            if source.get("page"):
                item["pages"].add(source["page"])
            if item["quantity"] is not None:
                item["quantity"] = (
                    item["quantity"] + quantity * factor
                    if quantity is not None and factor
                    else None
                )
    return sorted(
        result.values(),
        key=lambda item: (
            not any(offer[0] is not None for offer in item["offers"]),
            not item["offers"],
            item["category"],
            canonical(item["name"]),
            item["spec"],
        ),
    )
