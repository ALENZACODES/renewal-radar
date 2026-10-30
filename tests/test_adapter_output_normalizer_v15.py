import pytest

from renewal.ocr.adapter_output_normalizer_v15 import (
    AdapterNormalizationError,
    detect_payload_kind,
    normalize_adapter_payload,
    normalize_docling_output,
    normalize_marker_output,
    normalize_olmocr_output,
    normalize_paddleocr_output,
    normalize_surya_output,
    normalize_unstructured_output,
    pages_from_spans,
    preview_adapter_payload,
    quality_signals,
    validate_normalized_packet,
)


MORTGAGE_TEXT = (
    "Mortgage date: 2022-03-01\n"
    "Outstanding mortgage balance at renewal: $480,000.00\n"
    "Contract rate: 4.39%\n"
    "Posted rate: 5.69%\n"
    "Contract discount: 1.30%\n"
    "Renewal interest rate: 5.49%\n"
    "Remaining amortization period: 240 months\n"
    "Maturity date: 2027-03-01\n"
    "Interest rate differential applies; penalty may be three months interest."
)


def docling_payload():
    return {
        "provider": "docling",
        "document": {
            "pages": [
                {
                    "page_no": 1,
                    "texts": [
                        {"text": MORTGAGE_TEXT, "confidence": 0.94, "bbox": [0, 0, 500, 700]},
                    ],
                    "tables": [
                        {"caption": "Rate table", "rows": [["Posted", "5.69%"], ["Contract", "4.39%"]]},
                    ],
                }
            ]
        },
    }


def unstructured_payload():
    return [
        {
            "type": "NarrativeText",
            "text": MORTGAGE_TEXT,
            "metadata": {"page_number": 1, "coordinates": [0, 0, 500, 700]},
            "detection_class_prob": 0.92,
        },
        {
            "type": "Table",
            "text": "Posted | 5.69%\nContract | 4.39%",
            "metadata": {"page_number": 1},
        },
    ]


def paddle_payload():
    return {
        "provider": "paddleocr",
        "ocr_result": [
            [[[0, 0], [500, 0], [500, 50], [0, 50]], [line, 0.91]]
            for line in MORTGAGE_TEXT.splitlines()
        ],
        "tables": [{"page_number": 1, "rows": [["Balance", "$480,000.00"], ["Rate", "4.39%"]]}],
    }


def surya_payload():
    return {
        "provider": "surya",
        "pages": [
            {
                "page_number": 1,
                "text_lines": [
                    {"text": line, "confidence": 0.89, "bbox": [0, index * 10, 500, index * 10 + 8]}
                    for index, line in enumerate(MORTGAGE_TEXT.splitlines(), 1)
                ],
                "layout_blocks": [{"type": "section", "text": "Mortgage renewal agreement", "bbox": [0, 0, 500, 20]}],
            }
        ],
    }


def marker_payload():
    return {
        "provider": "marker",
        "markdown": MORTGAGE_TEXT,
        "chunks": [{"page": 1, "text": "Prepayment penalty: interest rate differential", "type": "clause"}],
        "blocks": [{"page": 1, "type": "table", "rows": [["Term", "60 months"], ["Maturity", "2027-03-01"]]}],
    }


def olmocr_payload():
    return {
        "provider": "olmocr",
        "linearized_text": MORTGAGE_TEXT,
        "quality_flags": ["Check table ordering against source"],
    }


@pytest.mark.parametrize(
    "payload,kind",
    [
        (docling_payload(), "docling"),
        (unstructured_payload(), "unstructured"),
        (paddle_payload(), "paddleocr"),
        (surya_payload(), "surya"),
        (marker_payload(), "marker"),
        (olmocr_payload(), "olmocr"),
    ],
)
def test_detect_payload_kind_for_supported_shapes(payload, kind):
    assert detect_payload_kind(payload) == kind


def test_docling_normalizer_preserves_text_and_tables():
    spans, tables, issues = normalize_docling_output(docling_payload())
    assert spans
    assert tables
    assert not issues
    assert spans[0].source == "docling"
    assert "Mortgage date" in spans[0].text
    assert tables[0].rows[0] == ("Posted", "5.69%")


def test_unstructured_normalizer_handles_elements_and_table_text():
    spans, tables, issues = normalize_unstructured_output(unstructured_payload())
    assert spans
    assert tables
    assert not issues
    assert spans[0].kind == "narrativetext"
    assert tables[0].source == "unstructured"


def test_paddleocr_normalizer_handles_box_text_score_tuples():
    spans, tables, issues = normalize_paddleocr_output(paddle_payload())
    assert len(spans) >= 8
    assert tables
    assert not issues
    assert spans[0].bbox == (0.0, 0.0, 500.0, 50.0)
    assert spans[0].confidence == 0.91


def test_surya_normalizer_handles_lines_and_layout_blocks():
    spans, tables, issues = normalize_surya_output(surya_payload())
    assert spans
    assert not issues
    assert any(span.kind == "section" for span in spans)
    assert any("Contract rate" in span.text for span in spans)


def test_marker_normalizer_handles_markdown_chunks_and_tables():
    spans, tables, issues = normalize_marker_output(marker_payload())
    assert spans
    assert tables
    assert not issues
    assert any(span.kind == "clause" for span in spans)


def test_olmocr_normalizer_carries_quality_flags_into_issues():
    spans, tables, issues = normalize_olmocr_output(olmocr_payload())
    assert spans
    assert tables == []
    assert issues
    assert issues[0].source == "olmocr"


def test_normalize_adapter_payload_returns_ocr_pages_and_quality_flags():
    packet = normalize_adapter_payload(paddle_payload())
    assert packet["provider"] == "adapter-output-normalizer-v15"
    assert packet["adapter"] == "paddleocr"
    assert packet["span_count"] >= 8
    assert packet["table_count"] == 1
    assert packet["quality"]["has_money"] is True
    assert packet["quality"]["has_rate"] is True
    assert packet["quality"]["has_penalty_language"] is True
    assert packet["ocr_pages"][0]["page_number"] == 1
    assert "480,000" in packet["ocr_pages"][0]["text"]


def test_pages_from_spans_groups_text_by_page():
    spans, _, _ = normalize_paddleocr_output(paddle_payload())
    pages = pages_from_spans(spans)
    assert len(pages) == 1
    assert pages[0]["source_span_count"] == len(spans)
    assert pages[0]["mean_confidence"] == 0.91


def test_quality_signals_detect_review_reasons():
    spans, tables, issues = normalize_olmocr_output(olmocr_payload())
    quality = quality_signals(spans, tables, issues)
    assert quality["has_money"] is True
    assert quality["has_rate"] is True
    assert quality["has_date"] is True
    assert quality["review_required"] is True


def test_validate_normalized_packet_flags_missing_core_contract_evidence():
    packet = normalize_adapter_payload({"provider": "marker", "markdown": "Hello world"})
    validation = validate_normalized_packet(packet)
    messages = " ".join(issue["message"] for issue in validation["issues"])
    assert validation["valid_for_contract_review"] is True
    assert "No money amount" in messages
    assert "No interest-rate" in messages


def test_preview_adapter_payload_returns_validation_summary():
    preview = preview_adapter_payload(docling_payload())
    assert preview["provider"] == "adapter-payload-preview-v15"
    assert preview["summary"]["valid_for_contract_review"] is True
    assert preview["summary"]["span_count"] >= 1
    assert preview["ocr_pages"]


def test_unsupported_payload_raises_clear_error():
    with pytest.raises(AdapterNormalizationError):
        normalize_adapter_payload({"unknown": "shape"})
