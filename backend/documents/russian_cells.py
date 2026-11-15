"""Read Russian name/unit columns separately from Latin model/supplier fields."""

import csv
import io
import re
import subprocess
from bisect import bisect_left


def restore_names(record):
    """Recover a name if an older numeric pass replaced its text with digits."""
    text = record.get("analysis_text", "")
    layout = record.get("analysis_layout", {})
    titles = set(re.findall(r"(C\d+–C\d+)=Наименован", text, re.I))
    if not titles:
        return record
    original = {
        (row.get("column"), row.get("top")): row["before"]
        for row in record.get("text_corrections", [])
        if re.search(r"[а-яё]{3,}", row["before"].split(" [OCR")[0], re.I)
    }
    replacements = []
    for line in layout.get("lines", []):
        match = re.match(r"(C\d+–C\d+)=(.*?)\s*\|\s*$", text[line["start"] : line["end"]], re.S)
        if not match or match[1] not in titles:
            continue
        if re.search(r"[а-яё]{3,}", match[2].split(" [OCR")[0], re.I):
            continue
        value = original.get((match[1], line["top"]))
        if value:
            replacements.append((line, f"{match[1]}={value} | "))
    if not replacements:
        return record
    return remap_text(record, replacements)


def remap_text(record, replacements):
    text = record["analysis_text"]
    original_layout = record["analysis_layout"]
    by_start = {cell["start"]: (cell["end"], value) for cell, value in replacements}
    offsets = sorted(by_start)
    cumulative = [0]
    for start in offsets:
        end, replacement = by_start[start]
        cumulative.append(cumulative[-1] + len(replacement) - (end - start))
    chunks, cursor = [], 0
    for start in offsets:
        end, replacement = by_start[start]
        chunks.extend((text[cursor:start], replacement))
        cursor = end
    chunks.append(text[cursor:])
    lines = [
        {
            **line,
            "start": line["start"] + cumulative[bisect_left(offsets, line["start"])],
            "end": line["end"] + cumulative[bisect_left(offsets, line["end"])],
        }
        for line in original_layout.get("lines", [])
    ]
    return {
        **record,
        "analysis_text": "".join(chunks),
        "analysis_layout": {**original_layout, "lines": lines},
    }


def refine(image, record):
    from PIL import Image, ImageOps

    text = record.get("analysis_text", "")
    layout = record.get("analysis_layout", {})
    cells = []
    for line in layout.get("lines", []):
        match = re.match(r"(C\d+–C\d+)=(.*?)\s*\|\s*$", text[line["start"] : line["end"]], re.S)
        if match:
            cells.append({**line, "column": match[1], "value": match[2].strip()})
    names = {cell["column"] for cell in cells if re.match(r"наименован", cell["value"], re.I)}
    units = {
        cell["column"] for cell in cells if re.match(r"единиц|ед\.?\s*изм", cell["value"], re.I)
    }
    selected = [
        cell
        for cell in cells
        if cell["column"] in names | units
        and not re.match(r"наименован|единиц|ед\.?\s*изм", cell["value"], re.I)
    ]
    quantities = {
        cell["column"]
        for cell in cells
        if re.match(r"кол|поверх|объем|объём|длин", cell["value"], re.I)
    } - (names | units)
    numbers = [
        cell
        for cell in cells
        if cell["column"] in quantities
        and not re.match(r"кол|поверх|объем|объём|длин", cell["value"], re.I)
    ]
    if not names or not selected:
        return {**record, "russian_cells": "not_applicable"}
    sx, sy = image.width / layout["width"], image.height / layout["height"]
    replacements, corrections = [], []
    for selected, numeric in ((selected, False), (numbers, True)):
        for start in range(0, len(selected), 32):
            batch = selected[start : start + 32]
            patches = []
            for cell in batch:
                box = (
                    round(cell["left"] * sx) + 4,
                    round(cell["top"] * sy) + 4,
                    round(cell["right"] * sx) - 3,
                    round(cell["bottom"] * sy) - 3,
                )
                patch = image.crop(box).convert("L")
                patch = patch.resize((patch.width * 2, patch.height * 2))
                patches.append(ImageOps.expand(patch, 12, fill="white"))
            canvas = Image.new(
                "L", (max(p.width for p in patches), sum(p.height + 30 for p in patches)), "white"
            )
            bounds, cursor = [], 0
            for patch in patches:
                canvas.paste(patch, (0, cursor))
                bounds.append((cursor, cursor + patch.height))
                cursor += patch.height + 30
            output = io.BytesIO()
            canvas.save(output, format="PNG")
            response = subprocess.run(
                [
                    "tesseract",
                    "stdin",
                    "stdout",
                    "-l",
                    "rus",
                    "--psm",
                    "6",
                    *(["-c", "tessedit_char_whitelist=0123456789.,/+-"] if numeric else []),
                    "tsv",
                ],
                input=output.getvalue(),
                capture_output=True,
                check=True,
                timeout=90,
            )
            words = [[] for _ in batch]
            for word in csv.DictReader(
                io.StringIO(response.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
            ):
                value = word.get("text", "").strip()
                if not value:
                    continue
                center = int(word["top"]) + int(word["height"]) / 2
                for index, (top, bottom) in enumerate(bounds):
                    if top <= center <= bottom:
                        words[index].append(
                            (
                                int(word["block_num"]),
                                int(word["par_num"]),
                                int(word["line_num"]),
                                int(word["left"]),
                                value,
                                float(word["conf"]),
                            )
                        )
                        break
            for cell, found in zip(batch, words):
                value = re.sub(r"\s+", " ", " ".join(word[-2] for word in sorted(found))).strip()
                if not value or value == cell["value"]:
                    continue
                confidence = sum(word[-1] for word in found) / len(found)
                if confidence < (0 if numeric else 35):
                    continue
                if numeric:
                    value = value.replace(" ", "")
                    if not re.fullmatch(r"\d+(?:[.,]\d+)?(?:/\d+(?:[.,]\d+)?)?", value):
                        continue
                    old = cell["value"].split(" [OCR")[0]
                    cleaned = re.sub(r"[^0-9.,/+\-]", "", old.replace(" ", ""))
                    if cleaned and (
                        cleaned != value
                        or old.replace(" ", "") != cleaned
                        or "[OCR" in cell["value"]
                    ):
                        value = cleaned + " [OCR расходится: " + value + "; проверить]"
                if cell["column"] in units and not re.match(r"единиц|ед\.?\s*изм", value, re.I):
                    key = re.sub(r"[\s.]", "", value.casefold())
                    if not re.fullmatch(
                        r"(?:м[²³23]?(?:/м[²³23?])?|мп|пм|шт|компл|кг|сист|систем|чел|чел/ч)", key
                    ):
                        continue
                # A unit/name pass cannot remove an existing dimension silently.
                # Both readings remain available for diagnosing any disagreement.
                segment = text[cell["start"] : cell["end"]]
                replacements.append((cell, segment[: segment.index("=") + 1] + value + " | "))
                corrections.append(
                    {
                        "column": cell["column"],
                        "top": cell["top"],
                        "before": cell["value"],
                        "after": value,
                        "confidence": round(confidence, 1),
                    }
                )
    return {
        **remap_text(record, replacements),
        "russian_cells": "rus-columns-v1",
        "text_corrections": corrections,
    }
