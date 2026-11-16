"""Route PDF pages by content and preserve a reversible coordinate system."""

from collections.abc import Iterator
from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path
from unicodedata import category

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps

from .schemas import Box, PageInfo


class SourceError(ValueError):
    """The document cannot be processed with the supplied limits or password."""


@dataclass(frozen=True, slots=True)
class Options:
    dpi: int = 300
    max_pixels: int = 80_000_000
    max_pages: int = 2000
    max_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        if not 300 <= self.dpi <= 600:
            raise ValueError("PDF render DPI must be between 300 and 600")
        if min(self.max_pixels, self.max_pages, self.max_bytes) < 1:
            raise ValueError("Resource limits must be positive")


DEFAULT_OPTIONS = Options()


@dataclass(frozen=True, slots=True)
class TextSpan:
    text: str
    font: str
    size: float
    bbox: Box
    direction: tuple[float, float]
    visible: bool


@dataclass(frozen=True, slots=True)
class PreparedPage:
    info: PageInfo
    spans: tuple[TextSpan, ...] = ()
    gray: np.ndarray | None = None
    binary: np.ndarray | None = None
    # Maps coordinates in the cleaned image back to PDF points or source pixels.
    pixel_to_source: tuple[tuple[float, ...], ...] | None = None
    deskew_degrees: float = 0.0
    render_dpi: int | None = None

    def source_box(self, image_box: Box) -> Box:
        if self.gray is None or self.pixel_to_source is None:
            raise ValueError("This page has no prepared raster")
        height, width = self.gray.shape
        if not (
            0 <= image_box.x0 < image_box.x1 <= width and 0 <= image_box.y0 < image_box.y1 <= height
        ):
            raise ValueError("Image box is outside the prepared raster")
        corners = np.array(
            [[x, y, 1] for x in (image_box.x0, image_box.x1) for y in (image_box.y0, image_box.y1)]
        )
        x, y = (corners @ np.asarray(self.pixel_to_source).T).T
        # The rotated canvas includes padding outside the source sheet.
        return Box(
            x0=max(0.0, float(x.min())),
            y0=max(0.0, float(y.min())),
            x1=min(self.info.width, float(x.max())),
            y1=min(self.info.height, float(y.max())),
        )


def check_size(path: Path, options: Options):
    if path.stat().st_size > options.max_bytes:
        raise SourceError("Input file exceeds the configured byte limit")


def open_pdf(path: Path, password: str | None, options: Options):
    check_size(path, options)
    try:
        document = pymupdf.open(path)
    except (RuntimeError, ValueError) as error:
        raise SourceError(f"Could not open PDF: {path.name}") from error
    try:
        if not document.is_pdf:
            raise SourceError("Expected a PDF document")
        if document.needs_pass and (not password or not document.authenticate(password)):
            raise SourceError("The PDF requires a valid password")
        if not 1 <= document.page_count <= options.max_pages:
            raise SourceError("PDF page count is outside the configured range")
    except Exception:
        document.close()
        raise
    return document


def spans_on_page(page) -> tuple[TextSpan, ...]:
    spans = []
    for item in page.get_texttrace():
        x0, y0, x1, y1 = item["bbox"]
        if x1 <= x0 or y1 <= y0:
            continue
        text = "".join(chr(code) if 0 <= code <= 0x10FFFF else "�" for code, *_ in item["chars"])
        if text.strip():
            spans.append(
                TextSpan(
                    text,
                    item["font"],
                    item["size"],
                    Box(x0=x0, y0=y0, x1=x1, y1=y1),
                    tuple(item["dir"]),
                    item["type"] != 3 and item.get("opacity", 1) > 0,
                )
            )
    return tuple(spans)


def image_coverage(page) -> float:
    # Estimate union coverage at 128×128. Overlapping images count only once.
    side = 128
    occupied = np.zeros((side, side), dtype=bool)
    width, height = page.rect.width, page.rect.height
    if min(width, height) <= 0:
        raise SourceError("PDF page has an empty crop box")
    for image in page.get_image_info():
        rect = pymupdf.Rect(image["bbox"]) & page.rect
        if rect.is_empty:
            continue
        x0, y0, x1, y1 = rect
        occupied[
            floor(y0 * side / height) : ceil(y1 * side / height),
            floor(x0 * side / width) : ceil(x1 * side / width),
        ] = True
    return float(occupied.mean())


def page_kind(coverage, spans, paths):
    visible_text = any(span.visible for span in spans)
    if coverage:
        return "mixed" if paths or visible_text else "raster"
    return "vector" if paths or visible_text else "blank"


def usable_text(spans):
    visible = [char for span in spans if span.visible for char in span.text if not char.isspace()]
    damaged = sum(char == "�" or category(char) in {"Cc", "Co", "Cs"} for char in visible)
    return (
        bool(visible) and damaged / len(visible) <= 0.15 and any(char.isalnum() for char in visible)
    )


def raster_limit(width, height, limit):
    if width * height > limit:
        raise SourceError("Raster exceeds the pixel limit at the requested DPI")


def render_gray(page, options: Options, clip=None):
    rect = page.rect if clip is None else clip
    scale = options.dpi / 72
    size = (rect * pymupdf.Matrix(scale, scale)).irect
    raster_limit(size.width, size.height, options.max_pixels)
    pixmap = page.get_pixmap(
        dpi=options.dpi, colorspace=pymupdf.csGRAY, alpha=False, clip=clip, annots=False
    )
    gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
    return gray, pixmap.x, pixmap.y


def skew_angle(gray) -> float:
    height, width = gray.shape
    scale = min(1.0, 1800 / max(width, height))
    preview = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(preview, 60, 180)
    shortest = max(30, min(preview.shape) // 8)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, 45, minLineLength=shortest, maxLineGap=12)
    if lines is None:
        return 0.0
    vectors = lines[:, 0, 2:] - lines[:, 0, :2]
    angles = (np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0])) + 45) % 90 - 45
    lengths = np.linalg.norm(vectors, axis=1)
    nearest = np.abs(angles) <= 12
    if nearest.sum() < 3:
        return 0.0
    indices = np.argsort(angles[nearest])
    angles, lengths = angles[nearest][indices], lengths[nearest][indices]
    median = angles[np.searchsorted(lengths.cumsum(), lengths.sum() / 2)]
    support = lengths[np.abs(angles - median) <= 1.0].sum() / lengths.sum()
    return float(median) if support >= 0.65 and abs(median) >= 0.15 else 0.0


def clean_raster(gray, options: Options):
    # Estimate skew on a preview but preserve the full resolution for OCR.
    height, width = gray.shape
    angle = skew_angle(gray) if min(width, height) >= 40 else 0.0
    rotation = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    if angle:
        cosine, sine = abs(rotation[0, 0]), abs(rotation[0, 1])
        out_width = ceil(width * cosine + height * sine)
        out_height = ceil(width * sine + height * cosine)
        raster_limit(out_width, out_height, options.max_pixels)
        rotation[:, 2] += [(out_width - width) / 2, (out_height - height) / 2]
        gray = cv2.warpAffine(gray, rotation, (out_width, out_height), borderValue=255)
    # Mild denoising avoids removing the small marks in diameter and tolerance glyphs.
    denoised = cv2.GaussianBlur(gray, (3, 3), 0.55)
    block_size = min(41, (min(gray.shape) - 1) | 1)
    if block_size >= 3 and min(gray.shape) >= 3:
        binary = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, 10
        )
    else:
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    inverse = np.vstack((cv2.invertAffineTransform(rotation), [0, 0, 1]))
    return gray, binary, inverse, angle


def prepare_pdf(
    path: Path, options=DEFAULT_OPTIONS, *, password=None, numbers=None, rasterize=True
) -> Iterator[PreparedPage]:
    """Hold at most one prepared page in memory when results are consumed as a stream."""
    with open_pdf(path, password, options) as document:
        selected = sorted(set(numbers)) if numbers else range(1, document.page_count + 1)
        if any(not 1 <= number <= document.page_count for number in selected):
            raise SourceError("Requested page is outside the PDF")
        for number in selected:
            page = document[number - 1]
            rotation = page.rotation
            page.set_rotation(0)
            spans = spans_on_page(page)
            coverage = image_coverage(page)
            paths = any(
                kind in {"fill-path", "stroke-path", "fill-shade"}
                for kind, *_ in page.get_bboxlog()
            )
            kind = page_kind(coverage, spans, paths)
            info = PageInfo(
                number=number,
                kind=kind,
                space="pdf_pt",
                width=page.rect.width,
                height=page.rect.height,
                rotation=rotation,
                raster_coverage=coverage,
                ocr_required=kind in {"raster", "mixed"}
                or (kind == "vector" and not usable_text(spans)),
            )
            if not rasterize or not info.ocr_required:
                yield PreparedPage(info, spans)
                continue
            gray, px, py = render_gray(page, options)
            gray, binary, inverse, angle = clean_raster(gray, options)
            points = 72 / options.dpi
            render_to_pdf = np.array(
                [[points, 0, px * points], [0, points, py * points], [0, 0, 1]]
            )
            matrix = (render_to_pdf @ inverse)[:2]
            yield PreparedPage(
                info, spans, gray, binary, tuple(map(tuple, matrix)), angle, options.dpi
            )


def open_fragment(path: Path, options: Options):
    check_size(path, options)
    with Image.open(path) as source:
        raster_limit(source.width, source.height, options.max_pixels)
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(background, rgba).convert("L")


def prepare_fragment(path: Path, options=DEFAULT_OPTIONS) -> PreparedPage:
    with open_fragment(path, options) as image:
        source = np.array(image)
    gray, binary, inverse, angle = clean_raster(source, options)
    info = PageInfo(
        number=1,
        kind="raster",
        space="image_px",
        width=source.shape[1],
        height=source.shape[0],
        raster_coverage=1.0,
        ocr_required=True,
    )
    return PreparedPage(
        info,
        gray=gray,
        binary=binary,
        pixel_to_source=tuple(map(tuple, inverse[:2])),
        deskew_degrees=angle,
    )
