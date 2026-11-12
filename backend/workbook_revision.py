import hashlib
import io
import json
from copy import copy
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.xml.functions import tostring

from .workbook_journal import is_journal, manual_fill


def package_parts(content):
    with ZipFile(io.BytesIO(content)) as archive:
        return {
            part.filename: (part.file_size, part.CRC)
            for part in archive.infolist()
            if not part.filename.startswith("docProps/")
        }


def load(content):
    book = load_workbook(io.BytesIO(content))
    if sum(sheet.max_row * sheet.max_column for sheet in book) > 3_000_000:
        raise ValueError("Таблица слишком большая для сравнения версий.")
    return book


def style_signature(cell):
    return (
        cell.number_format,
        *(
            tostring(copy(getattr(cell, name)).to_tree())
            for name in (
                "font",
                "fill",
                "border",
                "alignment",
                "protection",
            )
        ),
    )


def cell_value(cell):
    value = cell.value
    if cell.data_type == "f" and not isinstance(value, str):
        return (cell.data_type, tuple(sorted(dict(value).items())), getattr(value, "text", None))
    return (cell.data_type, value)


def snapshot(content):
    styles = {}
    result = {}
    for sheet in load(content):
        values, formats = {}, {}
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None or cell.comment:
                    values[cell.coordinate] = (
                        cell_value(cell),
                        (cell.comment.author, cell.comment.text) if cell.comment else None,
                    )
                if cell.has_style:
                    if cell.style_id not in styles:
                        styles[cell.style_id] = style_signature(cell)
                    formats[cell.coordinate] = styles[cell.style_id]
        layout = (
            tuple(sorted(str(group) for group in sheet.merged_cells.ranges)),
            tuple(sorted(str(key) for key, dim in sheet.row_dimensions.items() if dim.hidden)),
            tuple(sorted(str(key) for key, dim in sheet.column_dimensions.items() if dim.hidden)),
        )
        result[sheet.title] = (values, formats, layout)
    return result


def changes(before, after):
    if before == after or package_parts(before) == package_parts(after):
        return None
    first, second = snapshot(before), snapshot(after)
    content_changed = tuple(first) != tuple(second)
    format_changed = False
    locations = []
    for sheet in first.keys() & second.keys():
        old_values, old_formats, old_layout = first[sheet]
        new_values, new_formats, new_layout = second[sheet]
        content_changed |= old_layout != new_layout or old_values != new_values
        format_changed |= old_formats != new_formats
        for cell in sorted(old_values.keys() | new_values.keys()):
            if old_values.get(cell) != new_values.get(cell) and len(locations) < 3:
                locations.append(f"{sheet} · {cell}")
    if content_changed:
        return {"kind": "data", "locations": locations}
    if format_changed:
        return {"kind": "appearance", "locations": []}
    return None


def colors(content):
    result = {}
    fills = {}
    for sheet in load(content):
        generated = is_journal(sheet)
        for row in sheet.iter_rows():
            colored = []
            for cell in row:
                if not cell.has_style or not getattr(cell.fill, "fill_type", None):
                    continue
                if generated and not manual_fill(cell):
                    continue
                if cell.style_id not in fills:
                    fills[cell.style_id] = hashlib.sha256(
                        tostring(copy(cell.fill).to_tree())
                    ).hexdigest()[:16]
                colored.append((cell.column, fills[cell.style_id]))
            if colored:
                result[f"{sheet.title} · строка {row[0].row}"] = hashlib.sha256(
                    json.dumps(colored).encode()
                ).hexdigest()[:16]
    return result


def appearance_version(colors):
    return hashlib.sha256(json.dumps(colors, sort_keys=True).encode()).hexdigest()
