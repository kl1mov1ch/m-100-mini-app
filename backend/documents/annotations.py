import io
import math

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject, NameObject


def bands(boxes):
    rows = []
    for box in sorted(boxes, key=lambda item: (item["top"], item["left"])):
        values = [float(box.get(key, 0)) for key in ("left", "top", "width", "height")]
        if not all(math.isfinite(value) for value in values):
            continue
        left, top, width, height = values
        right, bottom = min(100, left + width), min(100, top + height)
        left, top = max(0, left), max(0, top)
        if right <= left or bottom <= top:
            continue
        height = min(bottom - top, 1.8)
        center = (top + bottom) / 2
        row = next(
            (row for row in rows if abs(row[1] - center) <= min(row[3], height) * 0.45), None
        )
        if row is None:
            rows.append([left, center, right, height])
        else:
            row[0], row[2] = min(row[0], left), max(row[2], right)
            row[3] = max(row[3], height)
    return rows


def annotated_pdf(source, groups):
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    marked = {}
    for group in groups:
        for item in group.get("sources", []):
            marked.setdefault(item["page"], []).extend(item.get("highlights", []))
    for number, boxes in marked.items():
        if not 1 <= number <= len(writer.pages):
            continue
        page = writer.pages[number - 1]
        if page.rotation:
            page.transfer_rotation_to_content()
        frame = page.mediabox
        for left, center, right, height in bands(boxes):
            x1 = float(frame.left) + float(frame.width) * left / 100
            x2 = float(frame.left) + float(frame.width) * right / 100
            y1 = float(frame.top) - float(frame.height) * (center + height / 2) / 100
            y2 = float(frame.top) - float(frame.height) * (center - height / 2) / 100
            annotation = Highlight(
                rect=(x1, y1, x2, y2),
                quad_points=ArrayObject(
                    [FloatObject(value) for value in (x1, y2, x2, y2, x1, y1, x2, y1)]
                ),
                highlight_color="FFE100",
                printing=True,
            )
            annotation[NameObject("/CA")] = FloatObject(0.32)
            writer.add_annotation(page_number=number - 1, annotation=annotation)
    writer.add_metadata(
        {
            "/Title": "M-100: источники выборки",
            "/Subject": "Жёлтым отмечены источники выборки; это не подтверждение оплаты.",
        }
    )
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()
