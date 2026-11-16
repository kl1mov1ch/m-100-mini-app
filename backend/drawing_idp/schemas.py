"""Typed interchange between the recognizer, validators and review tools."""

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

PageNumber = Annotated[int, Field(ge=1)]
Coordinate = Annotated[float, Field(allow_inf_nan=False)]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=512)]


def exact_decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,8})?", value):
        return Decimal(value)
    raise ValueError("Use a decimal string with a dot and up to eight fractional digits")


Quantity = Annotated[
    Decimal,
    Field(ge=0, le=Decimal(1000000000), max_digits=18, decimal_places=8),
    BeforeValidator(exact_decimal, json_schema_input_type=str),
]
Space = Literal["pdf_pt", "image_px"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Box(StrictModel):
    x0: Coordinate
    y0: Coordinate
    x1: Coordinate
    y1: Coordinate

    @model_validator(mode="after")
    def positive_area(self):
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("Box must have positive width and height")
        return self


class Region(StrictModel):
    """Origin is top-left. PDF boxes use unrotated page coordinates in points."""

    page: PageNumber
    bbox: Box
    space: Space = "pdf_pt"


class Observation[T](StrictModel):
    # Null denotes an unreadable field; the recognizer still identifies its cell.
    value: T | None
    confidence_score: Confidence
    source: Region
    raw_text: Annotated[str, Field(max_length=2000)] = ""


class PageInfo(StrictModel):
    number: PageNumber
    kind: Literal["vector", "raster", "mixed", "blank"]
    space: Space
    width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    rotation: Literal[0, 90, 180, 270] = 0
    raster_coverage: Confidence = 0.0
    ocr_required: bool = False


class Stamp(StrictModel):
    drawing_code: Observation[Text]
    title: Observation[Text] | None = None
    revision: Observation[Text] | None = None


class SpecificationRow(StrictModel):
    row_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")]
    name: Observation[Text]
    unit: Observation[Text]
    quantity: Observation[Quantity]
    unit_mass: Observation[Quantity] | None = None
    total_mass: Observation[Quantity] | None = None
    mass_unit: Literal["g", "kg", "t"] = "kg"
    material: Observation[Text] | None = None
    steel_grade: Observation[Text] | None = None
    standard: Observation[Text] | None = None
    part_number: Observation[Text] | None = None


class Callout(StrictModel):
    kind: Literal["diameter", "dimension", "tolerance", "roughness", "other"]
    # Literal engineering notation retained for later domain-specific parsing.
    text: Observation[Text]


class DrawingExtraction(StrictModel):
    stamp: Stamp
    specification: Annotated[list[SpecificationRow], Field(max_length=20000)] = Field(
        default_factory=list
    )
    callouts: Annotated[list[Callout], Field(max_length=20000)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_rows(self):
        if len({row.row_id for row in self.specification}) != len(self.specification):
            raise ValueError("Specification row IDs must be unique")
        return self


class ReviewItem(StrictModel):
    field: str
    reason: Literal[
        "low_confidence",
        "missing_value",
        "source_outside_page",
        "invalid_format",
        "invalid_unit",
        "mass_mismatch",
        "fuzzy_match",
        "evidence_mismatch",
    ]
    source: Region
    confidence_score: Confidence
    detail: str
    suggestion: str | None = None
    crop_path: str | None = None


class Correction(StrictModel):
    field: str
    original: str
    value: str
    method: Literal["catalogue_confusable"]


class ValidatedRow(StrictModel):
    row: SpecificationRow
    calculated_mass: Decimal | None = None
    needs_review: bool


class DrawingResult(StrictModel):
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    pages: list[PageInfo]
    stamp: Stamp
    rows: list[ValidatedRow]
    callouts: list[Callout]
    corrections: list[Correction]
    review_queue: list[ReviewItem]
    needs_review: bool
