"""Calibrate numeric glyphs from a table's own numbered column header.

Some CAD fonts make Tesseract read a 1 as a 7. A validated 1..N header
provides labelled shapes in the same font, without learning any quantities.
"""

import re


def components(image):
    import numpy as np

    pixels = np.asarray(image.convert("L")) < 150
    result = []
    for y, x in zip(*np.nonzero(pixels)):
        if not pixels[y, x]:
            continue
        stack, points = [(int(y), int(x))], []
        pixels[y, x] = False
        while stack:
            row, column = stack.pop()
            points.append((row, column))
            for yy in range(max(0, row - 1), min(pixels.shape[0], row + 2)):
                for xx in range(max(0, column - 1), min(pixels.shape[1], column + 2)):
                    if pixels[yy, xx]:
                        pixels[yy, xx] = False
                        stack.append((yy, xx))
        if len(points) >= 2:
            ys, xs = zip(*points)
            result.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, points))
    return sorted(result, key=lambda value: value[0])


def bitmap(component):
    import numpy as np
    from PIL import Image

    left, top, right, bottom, points = component
    image = np.zeros((bottom - top, right - left), dtype=np.uint8)
    for y, x in points:
        image[y - top, x - left] = 255
    return np.asarray(Image.fromarray(image).resize((20, 32))) / 255


def calibrate(image, record, fallback=None):
    import numpy as np

    text = record.get("analysis_text", "")
    layout = record.get("analysis_layout", {})
    cells = []
    for line in layout.get("lines", []):
        match = re.match(r"C\d+–C\d+=(.*?)\s*\|\s*$", text[line["start"] : line["end"]], re.S)
        before = list(re.finditer(r"Строка (\d+):", text[: line["start"]]))
        if match and before:
            column = text[line["start"] : line["end"]].split("=", 1)[0]
            cells.append(
                {**line, "row": int(before[-1][1]), "column": column, "value": match[1].strip()}
            )
    header = next(
        (cell["row"] for cell in cells if re.match(r"\s*наименован", cell["value"], re.I)), None
    )
    if header is None:
        return {**record, "digit_calibration": "not_applicable"}
    columns = sorted([cell for cell in cells if cell["row"] == header], key=lambda c: c["left"])
    quantity_columns = [
        cell for cell in columns if re.match(r"кол|поверх|объем|объём|длин", cell["value"], re.I)
    ]
    if not quantity_columns or len(columns) < 5:
        return {**record, "digit_calibration": "not_applicable"}
    labelled = []
    for row in sorted({cell["row"] for cell in cells if header < cell["row"] <= header + 3}):
        choices = []
        for cell in [c for c in cells if c["row"] == row]:
            column = min(range(len(columns)), key=lambda i: abs(columns[i]["left"] - cell["left"]))
            value = cell["value"].split(" [OCR")[0]
            if re.fullmatch(r"\d", value) and abs(columns[column]["left"] - cell["left"]) < 5:
                choices.append((cell, str(column + 1), value == str(column + 1)))
        if len(choices) >= 5 and sum(item[2] for item in choices) >= len(choices) * 0.6:
            labelled = choices
            break
    if not labelled and not fallback:
        return {**record, "digit_calibration": "unavailable"}
    sx, sy = image.width / layout["width"], image.height / layout["height"]

    def parts(cell):
        box = (
            round(cell["left"] * sx) + 4,
            round(cell["top"] * sy) + 4,
            round(cell["right"] * sx) - 3,
            round(cell["bottom"] * sy) - 3,
        )
        return components(image.crop(box))

    templates = {digit: np.asarray(values) for digit, values in (fallback or {}).items()}
    for cell, digit, _ in labelled:
        pieces = parts(cell)
        if pieces:
            main = max(pieces, key=lambda c: len(c[4]))
            templates[digit] = bitmap(main)
    replacements, corrections, uncertain = [], [], []
    number_row = labelled[0][0]["row"] if labelled else header + 1
    for cell in cells:
        if cell["row"] <= number_row or not any(
            abs(cell["left"] - column["left"]) <= 5 for column in quantity_columns
        ):
            continue
        old = cell["value"]
        base = old.split(" [OCR")[0].replace(" ", "")
        if not re.fullmatch(r"\d+(?:[.,]\d+)?", base):
            continue
        pieces = parts(cell)
        if not pieces:
            uncertain.append({"row": cell["row"], "column": cell["column"]})
            continue
        height = max(c[3] - c[1] for c in pieces)
        digits = [c for c in pieces if c[3] - c[1] >= height * 0.65 and len(c[4]) >= 8]
        # Never discard an extra digit-shaped component just to fit OCR's
        # shorter reading: two narrow ones can otherwise become a single 1.
        if len(digits) != sum(char.isdigit() for char in base):
            alternatives = re.findall(r"OCR расходится:\s*(\d+(?:[.,]\d+)?)", old)
            alternatives = [
                value for value in alternatives if sum(c.isdigit() for c in value) == len(digits)
            ]
            if len(alternatives) != 1:
                uncertain.append({"row": cell["row"], "column": cell["column"]})
                continue
            base = alternatives[0]
        characters, index, confident = list(base), 0, True
        for position, char in enumerate(characters):
            if not char.isdigit():
                continue
            glyph = bitmap(digits[index])
            index += 1
            if char == "0":
                continue
            scores = sorted(
                (float(np.mean(abs(glyph - template))), digit)
                for digit, template in templates.items()
            )
            if len(scores) < 2 or scores[0][0] > 0.23 or scores[1][0] - scores[0][0] < 0.035:
                confident = False
                continue
            if char in {"1", "7"} and scores[0][1] in {"1", "7"}:
                characters[position] = scores[0][1]
            elif scores[0][1] != char:
                # Do not clear an OCR disagreement merely because a different
                # digit looks plausible. Unsupported substitutions stay flagged.
                confident = False
        value = "".join(characters)
        if not confident:
            uncertain.append({"row": cell["row"], "column": cell["column"]})
        # A visible small component between digits independently preserves the
        # decimal separator when the second OCR pass dropped it.
        if pieces:
            separators = [c for c in pieces if c[3] - c[1] < height * 0.5 and len(c[4]) >= 2]
            split = next(
                (
                    i
                    for i in range(1, len(digits))
                    if any(
                        digits[i - 1][2] <= dot[0] <= digits[i][0]
                        and dot[1] >= min(d[1] for d in digits) + height * 0.55
                        for dot in separators
                    )
                ),
                None,
            )
            if split is not None and not re.search(r"[.,]", value):
                value = value[:split] + "," + value[split:]
            if "[OCR" in old and (not confident or (re.search(r"[.,]", base) and split is None)):
                continue
        if value != base or ("[OCR" in old and confident):
            segment = text[cell["start"] : cell["end"]]
            replacement = segment[: segment.index("=") + 1] + value + " | "
            replacements.append((cell, replacement))
            corrections.append(
                {
                    "row": cell["row"],
                    "before": old,
                    "after": value,
                    "method": "same-page-header-glyphs",
                }
            )
    lines = [dict(line) for line in layout.get("lines", [])]
    for cell, replacement in sorted(replacements, key=lambda pair: pair[0]["start"], reverse=True):
        delta = len(replacement) - (cell["end"] - cell["start"])
        text = text[: cell["start"]] + replacement + text[cell["end"] :]
        for line in lines:
            if line["start"] >= cell["end"]:
                line["start"] += delta
                line["end"] += delta
            elif line["start"] == cell["start"]:
                line["end"] += delta
    return {
        **record,
        "analysis_text": text,
        "analysis_layout": {**layout, "lines": lines},
        "digit_calibration": "header-glyphs-v1",
        "uncertain_numeric_cells": uncertain,
        "numeric_corrections": [*record.get("numeric_corrections", []), *corrections],
        "digit_templates": {digit: value.tolist() for digit, value in templates.items()},
    }
