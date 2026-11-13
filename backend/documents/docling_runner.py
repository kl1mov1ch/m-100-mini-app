"""Small Docling subprocess: native PDF text, OCR fallback, source coordinates.

Kept separate from the web process so parsing memory is released after each job.
No LLM calls, remote model services, or generated quantities are used here.
"""

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ENGINE = "docling-2.150.0-v2"


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def native_lines(document, page):
    size = document["pages"].get(str(page), document["pages"].get(page, {})).get("size", {})
    width, height = size.get("width", 1), size.get("height", 1)
    lines = []
    text = ""
    for item in document.get("texts", []):
        for source in item.get("prov", []):
            if source["page_no"] != page or not item.get("text", "").strip():
                continue
            box = source["bbox"]
            top, bottom = box["t"], box["b"]
            if box.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
                top, bottom = height - top, height - bottom
            start = len(text)
            text += item["text"].strip() + "\n"
            lines.append(
                {
                    "start": start,
                    "end": len(text) - 1,
                    "left": min(box["l"], box["r"]),
                    "top": min(top, bottom),
                    "right": max(box["l"], box["r"]),
                    "bottom": max(top, bottom),
                }
            )
    return {
        "text": text,
        "layout": {"width": width, "height": height, "lines": lines},
        "confidence": None,
    }


def structured_table(image, record):
    """Assign existing words to ruled cells using coordinates; never infer values."""
    import numpy as np

    ink = np.asarray(image.convert("L")) < 120

    def centers(indices):
        if not len(indices):
            return []
        return [
            int(np.mean(group))
            for group in np.split(indices, np.where(np.diff(indices) > 2)[0] + 1)
        ]

    horizontal = centers(np.flatnonzero(ink.mean(axis=1) > 0.55))
    cells = []
    for row, (top, bottom) in enumerate(zip(horizontal, horizontal[1:]), 1):
        if not 12 < bottom - top < image.height * 0.25:
            continue
        edges = centers(np.flatnonzero(ink[top + 3 : bottom - 2].mean(axis=0) > 0.8))
        if len(edges) < 5 or edges[-1] - edges[0] < image.width * 0.6:
            continue
        for left, right in zip(edges, edges[1:]):
            words = [
                word
                for word in record["layout"]["lines"]
                if left <= (word["left"] + word["right"]) / 2 <= right
                and top <= (word["top"] + word["bottom"]) / 2 <= bottom
            ]
            if words or ink[top + 4 : bottom - 3, left + 4 : right - 3].mean() > 0.001:
                value = " ".join(
                    record["text"][word["start"] : word["end"]]
                    for word in sorted(words, key=lambda w: (round(w["top"] / 8), w["left"]))
                )
                cells.append((row, left, top, right, bottom, value))
    if len(cells) < 12 or max(c[4] for c in cells) - min(c[2] for c in cells) < image.height * 0.4:
        return record
    # Read numeric cells in strips, not in one process per cell. Disagreement
    # remains explicit and blocks automatic use of that quantity downstream.
    import re

    from PIL import Image, ImageOps

    candidates = [
        index
        for index, (_, left, top, right, bottom, value) in enumerate(cells)
        if right - left < image.width * 0.1
        and bottom - top < image.height * 0.08
        and (not value or re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", value))
    ]
    for start in range(0, len(candidates), 24):
        batch = candidates[start : start + 24]
        patches = []
        for index in batch:
            _, left, top, right, bottom, _ = cells[index]
            patch = image.crop((left + 4, top + 4, right - 3, bottom - 3))
            patches.append(
                ImageOps.expand(patch.resize((patch.width * 2, patch.height * 2)), 16, fill="white")
            )
        canvas = Image.new(
            "L", (max(p.width for p in patches), sum(p.height + 24 for p in patches)), "white"
        )
        offsets, cursor = [], 0
        for patch in patches:
            canvas.paste(patch, (0, cursor))
            offsets.append((cursor, cursor + patch.height))
            cursor += patch.height + 24
        data = io.BytesIO()
        canvas.save(data, format="PNG")
        result = subprocess.run(
            [
                "tesseract",
                "stdin",
                "stdout",
                "--psm",
                "6",
                "-c",
                "tessedit_char_whitelist=0123456789.,+-",
                "tsv",
            ],
            input=data.getvalue(),
            capture_output=True,
            check=True,
            timeout=60,
        )
        values = ["" for _ in batch]
        for word in csv.DictReader(
            io.StringIO(result.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            if not word.get("text", "").strip():
                continue
            center = int(word["top"]) + int(word["height"]) / 2
            for index, (top, bottom) in enumerate(offsets):
                if top <= center <= bottom:
                    values[index] += word["text"].strip()
                    break
        for index, checked in zip(batch, values):
            if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", checked):
                continue
            *position, value = cells[index]
            if value and value.replace(",", ".") != checked.replace(",", "."):
                value += " [OCR расходится: " + checked + "; проверить]"
            elif not value:
                value = checked
            cells[index] = (*position, value)
    boundaries = centers(
        np.asarray(sorted({value for cell in cells for value in (cell[1], cell[3])}))
    )

    def column(value):
        return min(range(len(boundaries)), key=lambda index: abs(boundaries[index] - value)) + 1

    text = "Таблица: ячейки по строкам и колонкам. Номера строк — служебные, не количества.\n"
    lines, current = [], None
    for row, left, top, right, bottom, value in cells:
        if current != row:
            text += f"\nСтрока {row}: "
            current = row
        start = len(text)
        text += f"C{column(left)}–C{column(right)}={value} | "
        lines.append(
            {
                "start": start,
                "end": len(text),
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
            }
        )
    return {
        **record,
        "analysis_text": text,
        "analysis_layout": {**record["layout"], "lines": lines},
    }


def ocr(source, page, destination):
    import numpy as np
    from PIL import Image

    prefix = destination / f"render-{page}"
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-scale-to",
                "3000",
                "-singlefile",
                "-gray",
                "-png",
                str(source),
                str(prefix),
            ],
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with Image.open(prefix.with_suffix(".png")) as original:
            image = original.convert("L")
        pixels = np.array(image)
        ink = pixels < 120
        for axis in (0, 1):
            for edge in np.flatnonzero(ink.mean(axis=axis) > 0.55):
                if axis == 0:
                    pixels[:, max(0, edge - 1) : edge + 2] = 255
                else:
                    pixels[max(0, edge - 1) : edge + 2, :] = 255
        Image.fromarray(pixels).save(prefix.with_suffix(".ocr.png"))
        result = subprocess.run(
            [
                "tesseract",
                str(prefix.with_suffix(".ocr.png")),
                "stdout",
                "-l",
                "rus+eng",
                "--psm",
                "11",
                "tsv",
            ],
            check=True,
            timeout=180,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        width, height = image.size
        preview = image.copy()
        preview.thumbnail((2000, 2000))
        preview.save(destination / f"page-{page}.jpg", quality=85)
        text, lines, confidence = "", [], []
        for word in csv.DictReader(
            io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            value = word.get("text", "").strip()
            if not value:
                continue
            start = len(text)
            text += value + " "
            left, top = int(word["left"]), int(word["top"])
            lines.append(
                {
                    "start": start,
                    "end": len(text) - 1,
                    "left": left,
                    "top": top,
                    "right": left + int(word["width"]),
                    "bottom": top + int(word["height"]),
                }
            )
            if float(word["conf"]) >= 0:
                confidence.append(float(word["conf"]))
        # Restore reading order geometrically, rather than Tesseract's block order.
        bands = []
        for line in sorted(lines, key=lambda row: (row["top"], row["left"])):
            center = (line["top"] + line["bottom"]) / 2
            band = next(
                (
                    row
                    for row in bands[-3:]
                    if abs(row["center"] - center) <= max(4, (line["bottom"] - line["top"]) * 0.45)
                ),
                None,
            )
            if band is None:
                band = {"center": center, "words": []}
                bands.append(band)
            band["words"].append({**line, "text": text[line["start"] : line["end"]]})
        ordered, layout = "", []
        for band in sorted(bands, key=lambda row: row["center"]):
            for line in sorted(band["words"], key=lambda row: row["left"]):
                start = len(ordered)
                ordered += line["text"] + " "
                layout.append(
                    {
                        **{k: v for k, v in line.items() if k not in {"text", "start", "end"}},
                        "start": start,
                        "end": len(ordered) - 1,
                    }
                )
            ordered += "\n"
        return structured_table(
            image,
            {
                "text": ordered,
                "layout": {"width": width, "height": height, "lines": layout},
                "confidence": sum(confidence) / len(confidence) if confidence else 0,
                "method": "docling+tesseract",
            },
        )
    finally:
        prefix.with_suffix(".png").unlink(missing_ok=True)
        prefix.with_suffix(".ocr.png").unlink(missing_ok=True)


def convert(source, destination, signature, pages=None):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import NativePdfPipelineOptions
    from docling.document_converter import DocumentConverter, NativePdfFormatOption
    from docling_parse.pdf_parser import DoclingPdfParser

    destination.mkdir(parents=True, exist_ok=True)
    # Read the page count without retaining raster images or model weights.
    parser = DoclingPdfParser()
    parsed = parser.load(str(source))
    total = parsed.number_of_pages()
    options = NativePdfPipelineOptions(
        parser_threads=1, generate_page_images=False, generate_picture_images=False
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: NativePdfFormatOption(pipeline_options=options)},
    )
    # Specifications usually follow drawings. Make their text searchable first,
    # while the final archive always contains every page in document order.
    selected = pages or list(range(total, 0, -1))
    for done, number in enumerate(selected):
        path = destination / f"page-{number}.json"
        cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if cached.get("source") == signature and cached.get("engine") == ENGINE:
            write_json(
                destination / "progress.json",
                {"done": done + 1, "total": len(selected), "page": number},
            )
            continue
        write_json(
            destination / "progress.json", {"done": done, "total": len(selected), "page": number}
        )
        result = converter.convert(source, page_range=(number, number))
        document = result.document.export_to_dict()
        page = native_lines(document, number)
        if len(page["text"].strip()) < 30:
            page = ocr(source, number, destination)
        page.update(source=signature, engine=ENGINE)
        write_json(path, page)
        write_json(
            destination / "progress.json",
            {"done": done + 1, "total": len(selected), "page": number},
        )
    if all(
        (destination / f"page-{number}.json").is_file()
        and (lambda value: value.get("source") == signature and value.get("engine") == ENGINE)(
            json.loads((destination / f"page-{number}.json").read_text(encoding="utf-8"))
        )
        for number in range(1, total + 1)
    ):
        temporary = destination / "document.md.tmp"
        with temporary.open("w", encoding="utf-8") as target:
            for number in range(1, total + 1):
                page = json.loads((destination / f"page-{number}.json").read_text(encoding="utf-8"))
                target.write(f"\n\n## Страница {number}\n\n{page['text']}")
        temporary.replace(destination / "document.md")
        write_json(
            destination / "complete.json", {"source": signature, "pages": total, "engine": ENGINE}
        )


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("source", type=Path)
    cli.add_argument("destination", type=Path)
    cli.add_argument("--signature", default="")
    cli.add_argument("--pages", nargs="+", type=int)
    args = cli.parse_args()
    signature = args.signature or hashlib.sha256(args.source.read_bytes()).hexdigest()
    started = time.monotonic()
    convert(args.source, args.destination, signature, args.pages)
    if sys.platform != "win32":
        import resource

        print(
            f"elapsed={time.monotonic() - started:.1f}s peak_kb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}",
            file=sys.stderr,
        )
