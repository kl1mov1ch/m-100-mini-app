import csv
import io
import re

import numpy as np
from PIL import Image, ImageOps

from .execution import run


def centers(indices):
    if not len(indices):
        return []
    groups = np.split(indices, np.where(np.diff(indices) > 2)[0] + 1)
    return [int(np.mean(group)) for group in groups]


def cells(image):
    ink = np.asarray(image.convert("L")) < 120
    rows = centers(np.flatnonzero(ink.mean(axis=1) > 0.55))
    found = []
    for index, (top, bottom) in enumerate(zip(rows, rows[1:])):
        if bottom - top < 12 or bottom - top > image.height * 0.25:
            continue
        columns = centers(np.flatnonzero(ink[top + 3 : bottom - 2].mean(axis=0) > 0.8))
        if len(columns) < 5 or columns[-1] - columns[0] < image.width * 0.6:
            continue
        row = []
        for column, (left, right) in enumerate(zip(columns, columns[1:])):
            if right - left < 12:
                continue
            box = (left + 4, top + 4, right - 3, bottom - 3)
            content = ink[box[1] : box[3], box[0] : box[2]]
            if not content.size or content.mean() < 0.001:
                continue
            row.append({"row": index + 1, "column": column + 1, "box": box})
        found.extend(row)
    if (
        found
        and max(item["box"][3] for item in found) - min(item["box"][1] for item in found)
        < image.height * 0.4
    ):
        return []
    return found if 12 <= len(found) <= 400 else []


def recognize(image_path):
    with Image.open(image_path) as original:
        image = original.convert("L")
    entries = cells(image)
    if not entries:
        return None
    for start in range(0, len(entries), 24):
        batch = entries[start : start + 24]
        patches = [ImageOps.expand(image.crop(item["box"]), 16, fill="white") for item in batch]
        width = max(patch.width for patch in patches)
        height = sum(patch.height + 30 for patch in patches)
        if width * height > 16000000:
            return None
        canvas = Image.new("L", (width, height), "white")
        cursor = 0
        for item, patch in zip(batch, patches):
            canvas.paste(patch, (0, cursor))
            item["offset"] = cursor
            item["end"] = cursor + patch.height
            item["words"] = []
            cursor += patch.height + 30
        data = io.BytesIO()
        canvas.save(data, format="PNG")
        output = run(
            ["tesseract", "stdin", "stdout", "-l", "rus+eng", "--psm", "6", "tsv"],
            input=data.getvalue(),
            capture_output=True,
            check=True,
            timeout=120,
        )
        for word in csv.DictReader(
            io.StringIO(output.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            text = word.get("text", "").strip()
            if not text:
                continue
            middle = int(word["top"]) + int(word["height"]) / 2
            target = next((item for item in batch if item["offset"] <= middle <= item["end"]), None)
            if target is not None:
                target["words"].append((int(word["top"]), int(word["left"]), text))
    boundaries = sorted({edge for item in entries for edge in (item["box"][0], item["box"][2])})
    positions = centers(np.asarray(boundaries))

    def column_at(value):
        return min(range(len(positions)), key=lambda index: abs(positions[index] - value)) + 1

    lines = []
    layout = []
    text = "Таблица: ячейки по строкам и колонкам. Номера строк — служебные, не количества.\n"
    current_row = None
    for item in entries:
        content = " ".join(word[2] for word in item["words"])
        if not content:
            continue
        if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", content):
            patch = ImageOps.expand(image.crop(item["box"]), 12, fill="white")
            patch = patch.resize((patch.width * 2, patch.height * 2), Image.Resampling.LANCZOS)
            data = io.BytesIO()
            patch.save(data, format="PNG")
            checked = (
                run(
                    [
                        "tesseract",
                        "stdin",
                        "stdout",
                        "--psm",
                        "7",
                        "-c",
                        "tessedit_char_whitelist=0123456789.,+-",
                    ],
                    input=data.getvalue(),
                    capture_output=True,
                    check=True,
                    timeout=20,
                )
                .stdout.decode("utf-8")
                .strip()
            )
            if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", checked) and checked.replace(
                ",", "."
            ) != content.replace(",", "."):
                content = content + " [OCR расходится: " + checked + "; проверить]"
        left, top, right, bottom = item["box"]
        if current_row != item["row"]:
            text += f"\nСтрока {item['row']}: "
            current_row = item["row"]
        line = f"C{column_at(left)}–C{column_at(right)}={content} | "
        layout.append(
            {
                "start": len(text),
                "end": len(text) + len(line),
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
            }
        )
        text += line
        lines.append(line)
    if len(lines) < 12:
        return None
    return {"text": text, "layout": {"width": image.width, "height": image.height, "lines": layout}}
