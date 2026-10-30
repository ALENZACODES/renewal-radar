from renewal.ocr.engines import (
    AutoOCREngine,
    EasyOCREngine,
    PaddleOCREngine,
    RapidOCREngine,
    _box_bounds,
    _flatten_easyocr_result,
    _flatten_paddle_result,
    _flatten_rapidocr_result,
    choose_engine,
)
from renewal.ocr.camera import PreparedScan


def test_choose_engine_supports_optional_paddleocr():
    engine = choose_engine("paddleocr", language="eng")
    assert isinstance(engine, PaddleOCREngine)
    assert engine.language == "eng"


def test_choose_engine_supports_optional_easyocr_and_rapidocr():
    easy = choose_engine("easyocr", language="eng+fra")
    rapid = choose_engine("rapidocr", language="fra")
    assert isinstance(easy, EasyOCREngine)
    assert isinstance(rapid, RapidOCREngine)
    assert easy.language == "eng+fra"
    assert rapid.language == "fra"


def test_choose_engine_supports_auto_safe_router():
    engine = choose_engine("auto", language="eng")
    assert isinstance(engine, AutoOCREngine)
    assert engine.language == "eng"


def test_auto_router_returns_warning_page_when_everything_unavailable_or_fails():
    scan = PreparedScan(normalized_image=b"not-a-real-image", source_sha256="abc123")
    engine = AutoOCREngine(language="eng", order=("paddleocr", "docling", "easyocr", "rapidocr", "tesseract"))
    page = engine.recognize(scan)
    assert page.provider.startswith("auto:")
    assert page.text == "" or isinstance(page.text, str)
    assert page.source_hash == "abc123"
    assert page.warnings


def test_paddle_result_flattens_v3_dictionary_shape():
    payload = {
        "rec_texts": ["Contract rate", "4.39%"],
        "rec_scores": [0.95, 0.93],
        "rec_boxes": [[10, 20, 120, 40], [130, 20, 190, 40]],
    }
    rows = _flatten_paddle_result(payload)
    assert rows[0]["text"] == "Contract rate"
    assert rows[0]["confidence"] == 0.95
    assert rows[1]["text"] == "4.39%"


def test_paddle_result_flattens_v2_nested_shape():
    payload = [
        [
            [[[10, 20], [120, 20], [120, 40], [10, 40]], ("Posted rate", 0.91)],
            [[[130, 20], [190, 20], [190, 40], [130, 40]], ("5.69%", 0.89)],
        ]
    ]
    rows = _flatten_paddle_result(payload)
    assert [row["text"] for row in rows] == ["Posted rate", "5.69%"]
    assert rows[1]["confidence"] == 0.89


def test_paddle_box_bounds_handles_axis_aligned_and_polygon_boxes():
    assert _box_bounds([10, 20, 120, 45]) == (10, 20, 110, 25)
    assert _box_bounds([[10, 20], [120, 20], [120, 45], [10, 45]]) == (10, 20, 110, 25)
    assert _box_bounds(None) == (0, 0, 0, 0)


def test_easyocr_result_flattens_standard_shape():
    payload = [
        ([[10, 20], [120, 20], [120, 45], [10, 45]], "Contract discount", 0.94),
        ([[130, 20], [190, 20], [190, 45], [130, 45]], "1.30%", 0.92),
    ]
    rows = _flatten_easyocr_result(payload)
    assert rows[0]["text"] == "Contract discount"
    assert rows[0]["confidence"] == 0.94
    assert rows[1]["text"] == "1.30%"


def test_rapidocr_result_flattens_list_shape():
    payload = [
        ([[10, 20], [120, 20], [120, 45], [10, 45]], "Mortgage date", 0.91),
        ([[130, 20], [230, 20], [230, 45], [130, 45]], "2022-03-01", 0.88),
    ]
    rows = _flatten_rapidocr_result(payload)
    assert [row["text"] for row in rows] == ["Mortgage date", "2022-03-01"]
    assert rows[1]["confidence"] == 0.88
