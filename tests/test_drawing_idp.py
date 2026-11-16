import io
import json
from decimal import Decimal

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("cv2")
pytest.importorskip("rapidfuzz")

from backend.drawing_idp.__main__ import main
from backend.drawing_idp.preprocess import Options, SourceError, prepare_fragment, prepare_pdf
from backend.drawing_idp.schemas import Box, DrawingExtraction
from backend.drawing_idp.validation import Catalogue, read_extraction, validate_drawing


@pytest.fixture
def sources(tmp_path):
    drawing = tmp_path / "drawing.pdf"
    scan = tmp_path / "fragment.png"
    image = Image.new("L", (620, 430), 255)
    draw = ImageDraw.Draw(image)
    for y in range(75, 360, 40):
        draw.line((65, y, 540, y), fill=0, width=3)
    for x in (65, 190, 420, 540):
        draw.line((x, 75, x, 355), fill=0, width=3)
    image = image.rotate(-4, fillcolor=255)
    image.save(scan)
    stream = io.BytesIO()
    image.save(stream, "PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=180, height=120)
        page.insert_text((20, 35), "A-010 Diameter 100", fontname="helv")
        page.set_rotation(90)
        page = pdf.new_page(width=180, height=120)
        page.insert_image(page.rect, stream=stream.getvalue())
        page.insert_text((20, 35), "Invisible OCR", render_mode=3)
        page = pdf.new_page(width=180, height=120)
        page.insert_image(page.rect, stream=stream.getvalue())
        page.insert_text((20, 35), "Visible overlay")
        pdf.new_page(width=180, height=120)
        page = pdf.new_page(width=180, height=120)
        page.draw_line((20, 30), (80, 60))
        pdf.save(drawing)
    return drawing, scan


def test_routes_vector_raster_ocr_overlay_mixed_and_blank(sources):
    drawing, scan = sources
    vector, raster, mixed, blank, outlines = prepare_pdf(drawing)
    assert [p.info.kind for p in (vector, raster, mixed, blank)] == [
        "vector",
        "raster",
        "mixed",
        "blank",
    ]
    assert vector.info.rotation == 90 and vector.info.width == 180 and vector.gray is None
    assert vector.spans[0].text == "A-010 Diameter 100" and vector.spans[0].font
    assert not raster.spans[0].visible and raster.render_dpi == 300
    assert (
        outlines.info.kind == "vector" and outlines.info.ocr_required and outlines.gray is not None
    )
    assert raster.gray.shape[1] >= 750 and set(raster.binary.ravel()) <= {0, 255}
    fragment = prepare_fragment(scan)
    assert fragment.info.space == "image_px"
    assert fragment.deskew_degrees == pytest.approx(4, abs=0.6)
    box = fragment.source_box(Box(x0=150, y0=150, x1=190, y1=190))
    assert 0 <= box.x0 < box.x1 <= fragment.info.width
    with pytest.raises(SourceError, match="pixel limit"):
        list(prepare_pdf(drawing, Options(max_pixels=100), numbers=[2]))


def extraction_json():
    region = {"page": 1, "bbox": {"x0": 10, "y0": 12, "x1": 100, "y1": 40}}

    def observed(value, confidence=0.98, raw_text=""):
        return {
            "value": value,
            "confidence_score": confidence,
            "source": region,
            "raw_text": raw_text,
        }

    return {
        "stamp": {"drawing_code": observed("АБВГ.123456.001")},
        "specification": [
            {
                "row_id": "R1",
                "name": observed("Клапан противопожарныи"),
                "unit": observed("шт."),
                "quantity": observed("5", 0.71, "15"),
                "unit_mass": observed("2.5"),
                "total_mass": observed("15"),
                "steel_grade": observed("О9Г2С"),
                "standard": observed("ГОСТ 3262-75"),
                "part_number": observed("invalid value"),
            }
        ],
    }


def test_schema_and_validation_keep_field_evidence_and_mass_diagnostics(sources):
    drawing, _ = sources
    source_data = extraction_json()
    pages = [page.info for page in prepare_pdf(drawing, rasterize=False)]
    parsed = read_extraction(json.dumps(source_data).encode())
    result = validate_drawing(
        parsed,
        pages,
        "a" * 64,
        catalogue=Catalogue([("steel_grade", "09Г2С"), ("name", "Клапан противопожарный")]),
    )
    assert result.needs_review and result.rows[0].needs_review
    assert result.rows[0].calculated_mass == Decimal("12.5")
    assert result.rows[0].row.steel_grade.value == "09Г2С"
    assert result.corrections[0].original == "О9Г2С"
    assert result.rows[0].row.name.value == "Клапан противопожарныи"
    assert {item.reason for item in result.review_queue} == {
        "mass_mismatch",
        "evidence_mismatch",
        "low_confidence",
        "invalid_format",
        "fuzzy_match",
    }
    source_data["specification"][0]["quantity"]["value"] = 5
    payload = json.dumps(source_data).encode()
    with pytest.raises(ValidationError):
        DrawingExtraction.model_validate_json(payload)
    assert read_extraction(payload).specification[0].quantity.value is None


def test_cli_writes_result_review_crops_and_prepared_pngs(tmp_path, sources):
    drawing, _ = sources
    before = tmp_path / "preprocessed"
    assert main(["preprocess", str(drawing), str(before), "--page", "2"]) == 0
    assert (before / "page-0002-binary.png").stat().st_size > 0
    manifest = json.loads((before / "manifest.json").read_text(encoding="utf-8"))
    target = tmp_path / "validation"
    input_path = tmp_path / "extraction.json"
    candidate = extraction_json()
    candidate["specification"][0]["part_number"]["source"] = {
        "page": 9,
        "bbox": {"x0": 10, "y0": 12, "x1": 100, "y1": 40},
    }
    input_path.write_text(json.dumps(candidate), encoding="utf-8")
    assert main(["validate", str(drawing), str(target), "--extraction", str(input_path)]) == 0
    result = json.loads((target / "result.json").read_text(encoding="utf-8"))
    assert result["source_sha256"] == manifest["source_sha256"]
    assert result["rows"][0]["calculated_mass"] == "12.5"
    queue = result["review_queue"]
    assert all(item["crop_path"] is None for item in queue if item["source"]["page"] == 9)
    assert all(
        (target / item["crop_path"]).is_file() for item in queue if item["source"]["page"] == 1
    )
    assert len((target / "review.jsonl").read_text(encoding="utf-8").splitlines()) == len(queue)
    assert main(["validate", str(drawing), str(target), "--extraction", str(input_path)]) == 2
