"""Validate observed values without accepting quantities inferred by a model."""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path

from pydantic import ValidationError
from rapidfuzz import fuzz, process

from .schemas import (
    Correction,
    DrawingExtraction,
    DrawingResult,
    PageInfo,
    ReviewItem,
    ValidatedRow,
)

DRAWING_CODE = re.compile(r"[А-ЯЁ]{4}\.[0-9]{6}\.[0-9]{3}")
STANDARD = re.compile(
    r"(?:ГОСТ(?: Р)?(?: ISO| ИСО| IEC| МЭК)?|СТБ(?: ГОСТ| ISO| EN)?|ISO|EN|DIN)"
    r"\s+[0-9]+(?:[.-][0-9]+)*(?::[0-9]{4})?"
)
STEEL = re.compile(
    r"(?:СТ\s?[0-9]{1,2}(?:КП|ПС|СП)?|[0-9]{1,3}(?:[А-ЯЁ]{1,3}[0-9]{0,3}){0,6}"
    r"|S[0-9]{3}(?:JR|J0|J2|K2|N|NL|M|ML)?|AISI\s?[0-9]{3}[A-Z]?)"
)
ARTICLE = re.compile(r"(?=[А-ЯЁA-Z0-9._/\-]*[0-9])[А-ЯЁA-Z0-9][А-ЯЁA-Z0-9._/\-]{0,63}")
UNITS = frozenset(
    {
        "шт",
        "компл",
        "комплект",
        "м",
        "м2",
        "м3",
        "мм",
        "см",
        "кг",
        "г",
        "т",
        "ед",
        "л",
        "pcs",
        "pc",
        "set",
        "m",
        "m2",
        "m3",
        "kg",
        "g",
        "t",
    }
)
LOOKALIKES = str.maketrans("ABCEHKMOPTXYО", "АВСЕНКМ0РТХУ0")
NUMBER_FORMAT = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+)(?:[,.][0-9]+)?")


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).upper()
    return re.sub(r"\s+", " ", text.translate(str.maketrans("–—−", "---"))).strip()


def confusable_key(value: str) -> str:
    text = normalized(value).translate(LOOKALIKES)
    # Disambiguate 3/З only next to a digit, not in ordinary words.
    return re.sub(r"(?<=[0-9])З|З(?=[0-9])", "3", text)


@dataclass(frozen=True, slots=True)
class Match:
    value: str
    reason: str


class Catalogue:
    """CSV columns: kind (name/material/steel_grade) and value (approved spelling)."""

    def __init__(self, entries=()):
        by_type = defaultdict(dict)
        for kind, value in entries:
            if kind not in {"name", "material", "steel_grade"} or not value.strip():
                raise ValueError("Invalid catalogue kind or value")
            by_type[kind].setdefault(normalized(value), value.strip())
        self.entries = dict(by_type)
        self.confusables = {}
        for kind, values in self.entries.items():
            variants = defaultdict(list)
            for value in values.values():
                variants[confusable_key(value)].append(value)
            self.confusables[kind] = dict(variants)

    @classmethod
    def from_csv(cls, path: Path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"kind", "value"} <= set(reader.fieldnames or ()):
                raise ValueError("Catalogue requires CSV columns kind,value")
            return cls(((row["kind"] or "").strip(), row["value"] or "") for row in reader)

    def match(self, kind, text) -> Match | None:
        values = self.entries.get(kind, {})
        key = normalized(text)
        if not values or key in values:
            return None
        variants = self.confusables[kind].get(confusable_key(text), [])
        if len(variants) == 1:
            return Match(variants[0], "catalogue_confusable")
        # Close strings may be different valid grades or part sizes.
        # RapidFuzz produces a suggestion for an operator, never a replacement.
        hits = process.extract(key, list(values), scorer=fuzz.ratio, limit=2)
        if hits and hits[0][1] >= 87 and (len(hits) == 1 or hits[0][1] - hits[1][1] >= 5):
            return Match(values[hits[0][0]], "fuzzy_match")
        return None


@dataclass(frozen=True, slots=True)
class Rules:
    drawing_code_pattern: re.Pattern = DRAWING_CODE
    min_confidence: float = 0.88
    mass_absolute_kg: Decimal = Decimal("0.01")
    mass_relative: Decimal = Decimal("0.005")

    def __post_init__(self):
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("Minimum confidence must be between 0 and 1")
        if any(
            not value.is_finite() or value < 0
            for value in (self.mass_absolute_kg, self.mass_relative)
        ):
            raise ValueError("Mass tolerances must be finite and nonnegative")


DEFAULT_RULES = Rules()


def read_extraction(payload: bytes) -> DrawingExtraction:
    """Retain malformed field values as unreadable so valid evidence enters review."""
    try:
        return DrawingExtraction.model_validate_json(payload)
    except ValidationError as error:
        locations = {tuple(issue["loc"]) for issue in error.errors(include_input=False)}
        if not locations or any(
            len(location) < 3 or location[-1] not in {"value", "confidence_score"}
            for location in locations
        ):
            raise
        raw = json.loads(payload)
        for *parts, field in locations:
            observation = raw
            for part in parts:
                observation = observation[part]
            if field == "confidence_score":
                observation[field] = 0.0
            else:
                observation.setdefault("raw_text", str(observation.get(field, ""))[:2000])
                observation[field] = None
        return DrawingExtraction.model_validate_json(json.dumps(raw, ensure_ascii=False))


def source_in_page(source, pages_by_number):
    page = pages_by_number.get(source.page)
    box = source.bbox
    return (
        page is not None
        and page.space == source.space
        and (0 <= box.x0 < box.x1 <= page.width and 0 <= box.y0 < box.y1 <= page.height)
    )


def read_numeric_literal(raw: str) -> Decimal | None:
    value = raw.strip()
    if not NUMBER_FORMAT.fullmatch(value):
        return None
    return Decimal(re.sub(r"\s", "", value).replace(",", "."))


def validate_drawing(
    extraction: DrawingExtraction,
    pages: list[PageInfo],
    source_sha256: str,
    *,
    catalogue: Catalogue | None = None,
    rules=DEFAULT_RULES,
) -> DrawingResult:
    pages_by_number = {page.number: page for page in pages}
    if not pages or len(pages_by_number) != len(pages):
        raise ValueError("Source metadata must contain unique page numbers")
    catalogue = catalogue if catalogue is not None else Catalogue()
    reviews, corrections, rows = [], [], []

    def review(field, observation, reason, detail, suggestion=None):
        reviews.append(
            ReviewItem(
                field=field,
                reason=reason,
                detail=detail,
                source=observation.source,
                confidence_score=observation.confidence_score,
                suggestion=suggestion,
            )
        )

    def inspect(field, observation, *, pattern=None, catalogue_kind=None):
        if not source_in_page(observation.source, pages_by_number):
            review(
                field, observation, "source_outside_page", "Coordinates are outside the source page"
            )
        if observation.confidence_score < rules.min_confidence:
            review(
                field,
                observation,
                "low_confidence",
                "Field confidence is below the review threshold",
            )
        value = observation.value
        if value is None or (isinstance(value, str) and not value.strip()):
            review(field, observation, "missing_value", "The value is missing or unreadable")
            return observation
        if (
            isinstance(value, Decimal)
            and observation.raw_text
            and read_numeric_literal(observation.raw_text) != value
        ):
            review(
                field,
                observation,
                "evidence_mismatch",
                "Numeric value differs from the source literal",
            )
        if catalogue_kind and (match := catalogue.match(catalogue_kind, value)):
            if match.reason == "catalogue_confusable":
                corrections.append(
                    Correction(
                        field=field,
                        original=value,
                        value=match.value,
                        method="catalogue_confusable",
                    )
                )
                value = match.value
                observation = observation.model_copy(update={"value": value})
            else:
                review(
                    field,
                    observation,
                    "fuzzy_match",
                    "Confirm a similar catalogue entry",
                    match.value,
                )
        if pattern and not pattern.fullmatch(normalized(value)):
            review(
                field,
                observation,
                "invalid_format",
                "The value does not match the configured format",
            )
        return observation

    stamp_values = {}
    for field in type(extraction.stamp).model_fields:
        if (observation := getattr(extraction.stamp, field)) is not None:
            stamp_values[field] = inspect(
                f"stamp.{field}",
                observation,
                pattern=rules.drawing_code_pattern if field == "drawing_code" else None,
            )
    stamp = extraction.stamp.model_copy(update=stamp_values)
    for row in extraction.specification:
        start = len(reviews)
        changes = {}
        for field in (
            "name",
            "unit",
            "quantity",
            "unit_mass",
            "total_mass",
            "material",
            "steel_grade",
            "standard",
            "part_number",
        ):
            if (observation := getattr(row, field)) is not None:
                changes[field] = inspect(
                    f"rows.{row.row_id}.{field}",
                    observation,
                    pattern={
                        "steel_grade": STEEL,
                        "standard": STANDARD,
                        "part_number": ARTICLE,
                    }.get(field),
                    catalogue_kind=field if field in {"name", "material", "steel_grade"} else None,
                )
        row = row.model_copy(update=changes)
        if row.unit.value and normalized(row.unit.value).casefold().strip(".") not in UNITS:
            review(
                f"rows.{row.row_id}.unit", row.unit, "invalid_unit", "Unrecognized unit of measure"
            )
        calculated = None
        if row.quantity.value is not None and row.unit_mass and row.unit_mass.value is not None:
            with localcontext() as arithmetic:
                arithmetic.prec = 40
                calculated = row.quantity.value * row.unit_mass.value
            if row.total_mass and row.total_mass.value is not None:
                claimed = row.total_mass.value
                kg_per_unit = {"g": Decimal("0.001"), "kg": Decimal(1), "t": Decimal(1000)}[
                    row.mass_unit
                ]
                tolerance = max(
                    rules.mass_absolute_kg / kg_per_unit,
                    calculated * rules.mass_relative,
                )
                if abs(claimed - calculated) > tolerance:
                    review(
                        f"rows.{row.row_id}.total_mass",
                        row.total_mass,
                        "mass_mismatch",
                        f"Quantity × unit mass = {calculated} {row.mass_unit}",
                        str(calculated),
                    )
        rows.append(
            ValidatedRow(row=row, calculated_mass=calculated, needs_review=len(reviews) > start)
        )
    for index, callout in enumerate(extraction.callouts):
        inspect(f"callouts.{index}.text", callout.text)
    return DrawingResult(
        source_sha256=source_sha256,
        pages=pages,
        stamp=stamp,
        rows=rows,
        callouts=extraction.callouts,
        corrections=corrections,
        review_queue=reviews,
        needs_review=bool(reviews),
    )
