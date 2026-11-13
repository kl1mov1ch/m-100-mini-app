"""Select estimate tables by their parsed column headers, never drawing text."""

import re

ROWS = re.compile(r"Строка\s+(\d+)\s*:\s*(.*?)(?=\nСтрока\s+\d+\s*:|\Z)", re.S)
CELLS = re.compile(r"C(\d+)[–-]C(\d+)=(.*?)(?=\s*\|\s*C\d+[–-]C\d+=|\s*\|\s*$|\Z)", re.S)


def clean(value):
    value = value.casefold().replace("ё", "е")
    value = value.translate(str.maketrans("acekmoptx", "асекмортх"))
    return re.sub(r"[\s\-–.,:]+", "", value)


def estimate_table(record):
    """Return bounded table text and remap its source coordinates.

    A title mentioning a specification, or a small legend on a drawing, cannot
    qualify: actual name, volume and unit columns are required near the top.
    """
    text = record.get("analysis_text", "")
    rows = list(ROWS.finditer(text))
    if not rows:
        return None
    headers = []
    for index, row in enumerate(rows[:6]):
        cells = [(int(cell[1]), int(cell[2]), cell[3].strip()) for cell in CELLS.finditer(row[2])]
        short = [(left, right, clean(value)) for left, right, value in cells if len(value) < 170]
        names = [cell for cell in short if cell[2].startswith("наименован")]
        amounts = [
            cell
            for cell in short
            if (cell[2].startswith("кол") and len(cell[2]) < 24)
            or re.match(
                r"^(?:длина|длинавы|длина,|длинавыс|длина.*м$|поверх.*ност|объем|площад)", cell[2]
            )
        ]
        units = [
            cell
            for cell in short
            if re.match(r"^(?:единиц|едизм)", cell[2])
            or re.search(r"(?:м[²23?*]|(?:дли|выс|ност|объем).*м$)", cell[2])
        ]
        if (
            names
            and amounts
            and units
            and any(name[:2] != amount[:2] for name in names for amount in amounts)
        ):
            headers.append((index, min(c[0] for c in cells), max(c[1] for c in cells)))
    if not headers:
        return None
    start, left, right = headers[0]
    name_column = next(
        (int(cell[1]), int(cell[2]))
        for cell in CELLS.finditer(rows[start][2])
        if clean(cell[3]).startswith("наименован")
    )
    kept = []
    for row in rows[max(0, start - 1) :]:
        cells = list(CELLS.finditer(row[2]))
        if not cells:
            continue
        values = " ".join(c[3] for c in cells)
        if re.search(
            r"(?:разраб\w*|проверил|нормоконтроль|стадия\s+лист|изм\.\s+кол)", values, re.I
        ):
            break
        selected = [cell for cell in cells if int(cell[1]) >= left and int(cell[2]) <= right]
        if selected:
            kept.append((row, selected))
    if len(kept) < 3:
        return None
    layout = record.get("analysis_layout", record.get("layout", {}))
    selected_text = (
        "Таблица: ячейки по строкам и колонкам. Номера строк — служебные, не количества.\n"
    )
    lines = []
    names, previous_name = {}, ""
    for row, cells in kept:
        name_cell = next(
            (cell[3].strip() for cell in cells if (int(cell[1]), int(cell[2])) == name_column),
            "",
        )
        if re.search(r"[а-яА-Яa-zA-Z]{3,}", name_cell) and not clean(name_cell).startswith(
            "наименован"
        ):
            previous_name = name_cell
        if previous_name:
            names[int(row[1])] = previous_name
        selected_text += f"Строка {row[1]}: "
        for cell in cells:
            old_start = row.start(2) + cell.start()
            old_end = row.start(2) + cell.end()
            offset = len(selected_text) - old_start
            segment = cell[0].rstrip(" |") + " | "
            selected_text += segment
            for line in layout.get("lines", []):
                if old_start <= line["start"] < old_end:
                    lines.append(
                        {
                            **line,
                            "start": line["start"] + offset,
                            "end": min(line["end"] + offset, len(selected_text)),
                        }
                    )
        selected_text += "\n"
    return {
        "text": selected_text,
        "layout": {
            **layout,
            "lines": lines,
        },
        "rows": [int(row[1]) for row, _ in kept],
        "row_names": names,
        "headers": [int(rows[index][1]) for index, _, _ in headers],
    }
