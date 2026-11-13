import json
import re
import shutil
import subprocess

import numpy as np
from PIL import Image

from .execution import check_active, run


def classify_page(text):
    value = re.sub(r"\s+", " ", text.casefold().replace("ё", "е"))
    value = value.translate(str.maketrans("acekmoptx", "асекмортх"))
    value = re.sub(r"[-–]\s+", "", value)
    if re.search(r"ведомость\s+(?:чертежей|ссылочных)|общие\s+(?:данные|указания)", value):
        return "drawing"
    if re.search(
        r"спецификаци[яи]\s+(?:оборудован|издел|материал)|ведомость\s+(?:объем|объём|работ|материал|оборудован)",
        value,
    ):
        return "specification"
    headers = [
        bool(re.search(pattern, value))
        for pattern in (
            r"наименован",
            r"количеств|кол\.?\s*[-.]?\s*во|ко[лnп](?:\.|\b)|поверхност|объем|площад",
            r"единиц|ед\.\s*изм|масса|обозначение|м[²23]|шт\.|кг",
            r"характеристик|тип.?\s*марк|поз[. ]",
        )
    ]
    if headers[0] and headers[1] and sum(headers) >= 3:
        return "specification"
    if re.search(r"план\s+(?:на|систем|этажа|кровли)|аксонометр|схема\s|разрез\s", value):
        return "drawing"
    return "uncertain"


def inspect_page(source, number, destination, native_text=""):
    if native_text.strip():
        return {"page": number, "kind": classify_page(native_text), "method": "text"}
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return {"page": number, "kind": "uncertain", "method": "unavailable"}
    prefix = destination / f"index-{number}"
    image_path = prefix.with_suffix(".jpg")
    try:
        run(
            [
                "pdftoppm",
                "-f",
                str(number),
                "-l",
                str(number),
                "-scale-to",
                "3000",
                "-singlefile",
                "-jpeg",
                "-gray",
                str(source),
                str(prefix),
            ],
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with Image.open(image_path) as image:
            image = image.convert("L")
            top = image.crop((0, 0, image.width, int(image.height * 0.20)))
            bottom = image.crop((0, int(image.height * 0.88), image.width, image.height))
            # Remove long rules before reading the small column headers. Otherwise
            # OCR joins letters to the table grid and misses continuation sheets.
            cleaned = []
            for patch in (top, bottom):
                pixels = np.array(patch)
                ink = pixels < 120
                for axis in (0, 1):
                    indices = np.flatnonzero(ink.mean(axis=axis) > 0.55)
                    for edge in indices:
                        if axis == 0:
                            pixels[:, max(0, edge - 1) : edge + 2] = 255
                        else:
                            pixels[max(0, edge - 1) : edge + 2, :] = 255
                cleaned.append(Image.fromarray(pixels))
            top, bottom = cleaned
            strip = Image.new("L", (image.width, top.height + bottom.height + 30), "white")
            strip.paste(top, (0, 0))
            strip.paste(bottom, (0, top.height + 30))
            strip.save(prefix.with_suffix(".png"))
        check_active()
        result = run(
            [
                "tesseract",
                str(prefix.with_suffix(".png")),
                "stdout",
                "-l",
                "rus+eng",
                "--psm",
                "11",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=25,
        )
        return {
            "page": number,
            "kind": classify_page(result.stdout),
            "method": "heading_ocr",
            "heading": result.stdout[:1800],
        }
    except subprocess.SubprocessError:
        return {"page": number, "kind": "uncertain", "method": "timeout"}
    finally:
        image_path.unlink(missing_ok=True)
        prefix.with_suffix(".png").unlink(missing_ok=True)


def page_index(source, count, destination, native, saved, report):
    indexed = {row["page"]: row for row in saved}
    for number in range(count, 0, -1):
        check_active()
        if number in indexed:
            continue
        report(number, list(indexed.values()))
        result = native(number)
        indexed[number] = inspect_page(
            source, number, destination, result["text"] if result else ""
        )
        temporary = destination / "selection.tmp"
        temporary.write_text(
            json.dumps(list(indexed.values()), ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(destination / "selection.json")
        report(number, list(indexed.values()))
    return [indexed[number] for number in sorted(indexed)]
