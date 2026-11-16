"""Offline CLI for preprocessing, result validation and review packages."""

import argparse
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from math import ceil, floor
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf
from PIL import Image
from pydantic import ValidationError

from .preprocess import (
    Options,
    check_size,
    open_fragment,
    open_pdf,
    prepare_fragment,
    prepare_pdf,
    render_gray,
)
from .schemas import DrawingExtraction, DrawingResult, PageInfo
from .validation import (
    DRAWING_CODE,
    Catalogue,
    Rules,
    read_extraction,
    source_in_page,
    validate_drawing,
)


@contextmanager
def new_package(target: Path):
    # Publish atomically. A failed run retains any previously published package.
    if target.exists():
        raise FileExistsError(f"Output directory already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".drawing-idp-", dir=target.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        yield stage
        if target.exists():
            raise FileExistsError(f"Output directory already exists: {target}")
        stage.rename(target)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_pdf(path):
    return path.suffix.casefold() == ".pdf"


def fingerprint(path, options):
    check_size(path, options)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preprocess(source, target, options, numbers):
    digest = fingerprint(source, options)
    if numbers and not is_pdf(source) and set(numbers) != {1}:
        raise ValueError("An image fragment has only page 1")
    pages = (
        prepare_pdf(source, options, numbers=numbers)
        if is_pdf(source)
        else (prepare_fragment(source, options),)
    )
    with new_package(target) as stage:
        index = []
        for page in pages:
            stem = f"page-{page.info.number:04d}"
            meta = page.info.model_dump(mode="json")
            write_json(
                stage / f"{stem}.json",
                {
                    **meta,
                    "render_dpi": page.render_dpi,
                    "deskew_degrees": page.deskew_degrees,
                    "pixel_to_source": page.pixel_to_source,
                    "spans": [
                        {
                            "text": span.text,
                            "font": span.font,
                            "size": span.size,
                            "bbox": span.bbox.model_dump(),
                            "direction": span.direction,
                            "visible": span.visible,
                        }
                        for span in page.spans
                    ],
                },
            )
            if page.gray is not None and page.binary is not None:
                Image.fromarray(page.gray).save(stage / f"{stem}-gray.png")
                Image.fromarray(page.binary).save(stage / f"{stem}-binary.png")
            index.append(meta)
        write_json(stage / "manifest.json", {"source_sha256": digest, "pages": index})
    return {"pages": len(index)}


def save_review(result, source, stage, options):
    pages = {page.number: page for page in result.pages}
    queue = []
    cropped = {}
    pdf = is_pdf(source)
    reader = open_pdf(source, None, options) if pdf else open_fragment(source, options)
    with reader as document:
        for item in result.review_queue:
            location = item.source
            if not source_in_page(location, pages):
                queue.append(item)
                continue
            box = location.bbox
            key = (location.page, box.x0, box.y0, box.x1, box.y1)
            relative = cropped.get(key)
            if relative is None:
                relative = f"crops/{len(cropped) + 1:06d}.png"
                path = stage / relative
                path.parent.mkdir(exist_ok=True)
                if pdf:
                    page = document[location.page - 1]
                    page.set_rotation(0)
                    gray, _, _ = render_gray(
                        page, options, pymupdf.Rect(box.x0, box.y0, box.x1, box.y1)
                    )
                    Image.fromarray(gray).save(path, dpi=(options.dpi, options.dpi))
                else:
                    document.crop((floor(box.x0), floor(box.y0), ceil(box.x1), ceil(box.y1))).save(
                        path
                    )
                cropped[key] = relative
            queue.append(item.model_copy(update={"crop_path": relative}))
    with (stage / "review.jsonl").open("w", encoding="utf-8") as stream:
        for item in queue:
            stream.write(item.model_dump_json() + "\n")
    return result.model_copy(update={"review_queue": queue})


def validate(source, input_json, target, options, catalogue_file, pattern):
    with input_json.open("rb") as stream:
        payload = stream.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("Extraction JSON exceeds 16 MiB")
    extraction = read_extraction(payload)
    digest = fingerprint(source, options)
    if is_pdf(source):
        pages = [page.info for page in prepare_pdf(source, options, rasterize=False)]
    else:
        with open_fragment(source, options) as image:
            pages = [
                PageInfo(
                    number=1,
                    kind="raster",
                    space="image_px",
                    width=image.width,
                    height=image.height,
                    raster_coverage=1.0,
                    ocr_required=True,
                )
            ]
    result = validate_drawing(
        extraction,
        pages,
        digest,
        catalogue=Catalogue.from_csv(catalogue_file) if catalogue_file else None,
        rules=Rules(drawing_code_pattern=pattern),
    )
    with new_package(target) as stage:
        result = save_review(result, source, stage, options)
        (stage / "result.json").write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    return {"needs_review": result.needs_review, "review_items": len(result.review_queue)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("preprocess")
    prepare.add_argument("--page", type=int, action="append")
    check = commands.add_parser("validate")
    check.add_argument("--extraction", required=True, type=Path)
    check.add_argument("--catalogue", type=Path)
    check.add_argument("--drawing-code-pattern")
    for command in (prepare, check):
        command.add_argument("source", type=Path)
        command.add_argument("output", type=Path)
        command.add_argument("--dpi", type=int, default=300)
        command.add_argument("--max-pixels", type=int, default=80_000_000)
    schema = commands.add_parser("schema")
    schema.add_argument("--input", action="store_true", help="Print recognizer input schema")
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            model = DrawingExtraction if args.input else DrawingResult
            definition = model.model_json_schema(
                mode="validation" if args.input else "serialization"
            )
            print(
                json.dumps(
                    {"$schema": "https://json-schema.org/draft/2020-12/schema", **definition},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        options = Options(dpi=args.dpi, max_pixels=args.max_pixels)
        if args.command == "preprocess":
            result = preprocess(args.source, args.output, options, args.page)
        else:
            pattern = (
                re.compile(args.drawing_code_pattern) if args.drawing_code_pattern else DRAWING_CODE
            )
            result = validate(
                args.source, args.extraction, args.output, options, args.catalogue, pattern
            )
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, ValidationError, RuntimeError, re.error) as error:
        print(f"drawing-idp: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
