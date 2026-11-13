"""Recover diameter signs and dimensions from original table word images."""

import re

if __package__:
    from .glyph_numbers import bitmap, components
else:
    from glyph_numbers import bitmap, components


def read_dimensions(image, record, templates, diameter_template=None):
    import numpy as np

    text = record.get("analysis_text", "")
    layout = record.get("analysis_layout", {})
    cells = []
    for line in layout.get("lines", []):
        match = re.match(r"(C\d+–C\d+)=(.*?)\s*\|\s*$", text[line["start"] : line["end"]], re.S)
        prefixes = list(re.finditer(r"Строка (\d+):", text[: line["start"]]))
        if match and prefixes:
            cells.append(
                {**line, "column": match[1], "value": match[2], "row": int(prefixes[-1][1])}
            )
    name_columns = {
        cell["column"] for cell in cells if re.match(r"наименован", cell["value"], re.I)
    }
    name_cells = [cell for cell in cells if cell["column"] in name_columns]
    raw = record.get("layout", {})
    sx, sy = (
        image.width / raw.get("width", image.width),
        image.height / raw.get("height", image.height),
    )
    words = []
    for word in raw.get("lines", []):
        value = record.get("text", "")[word["start"] : word["end"]].strip(" ,;().")
        if not re.fullmatch(r"[#Øø⌀Фф]?\d{2,5}|\d{2,5}[xх×]\d{2,5}", value):
            continue
        parent = next(
            (
                cell
                for cell in name_cells
                if cell["left"] <= (word["left"] + word["right"]) / 2 <= cell["right"]
                and cell["top"] <= (word["top"] + word["bottom"]) / 2 <= cell["bottom"]
            ),
            None,
        )
        if parent:
            crop = image.crop(
                (
                    round(word["left"] * sx) - 1,
                    round(word["top"] * sy) - 1,
                    round(word["right"] * sx) + 1,
                    round(word["bottom"] * sy) + 1,
                )
            )
            pieces = components(crop)
            if pieces:
                height = max(piece[3] - piece[1] for piece in pieces)
                pieces = [piece for piece in pieces if piece[3] - piece[1] >= height * 0.65]
            words.append((value, pieces, parent["row"]))
    numeric = {key: np.asarray(value) for key, value in templates.items() if key.isdigit()}
    diameter = np.asarray(diameter_template) if diameter_template is not None else None
    for value, pieces, _ in words:
        if value[0] in "#Øø⌀Фф" and len(pieces) == len(value):
            shape = bitmap(pieces[0])
            closest_digit = min(
                (float(np.mean(abs(shape - v))) for v in numeric.values()), default=1
            )
            if closest_digit > 0.08:
                diameter = shape
                break
    dimensions = {}
    for value, pieces, row in words:
        rectangle = re.fullmatch(r"(\d{2,5})[xх×](\d{2,5})", value)
        if rectangle:
            dimensions[row] = {
                "kind": "rectangle",
                "a_mm": int(rectangle[1]),
                "b_mm": int(rectangle[2]),
                "source": value,
            }
            continue
        if diameter is None or not pieces:
            continue
        shape = bitmap(pieces[0])
        match = float(np.mean(abs(shape - diameter)))
        closest_digit = min((float(np.mean(abs(shape - v))) for v in numeric.values()), default=1)
        if match > 0.18 or closest_digit - match < 0.035:
            continue
        digits = re.sub(r"^[#Øø⌀Фф]", "", value)
        if value[0].isdigit() and len(pieces) == len(digits):
            digits = digits[1:]
        if not digits or len(pieces) - 1 != len(digits):
            continue
        chars = list(digits)
        for index, piece in enumerate(pieces[1:]):
            shape = bitmap(piece)
            scores = sorted((float(np.mean(abs(shape - v))), key) for key, v in numeric.items())
            if len(scores) > 1 and scores[0][0] < 0.1 and scores[1][0] - scores[0][0] > 0.05:
                chars[index] = scores[0][1]
        dimensions[row] = {
            "kind": "round",
            "diameter_mm": int("".join(chars)),
            "source": value,
            "reading": "Ø" + "".join(chars),
        }
    return dimensions, diameter.tolist() if diameter is not None else None
