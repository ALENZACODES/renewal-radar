import pytest

from renewal.ocr.fields import (
    OCRFieldError,
    OCRTextPage,
    apply_corrections,
    confidence_label,
    document_metrics,
    extract_ocr_fields,
    field_specs,
    find_candidates,
    flatten_ocr_text,
    mortgage_draft,
    parse_date_value,
    parse_enum,
    parse_money,
    parse_percent,
    prepare_pages,
    redact_sensitive_text,
    repair_numeric_token,
    review_status,
    summarize_review_decision,
)


SAMPLE_PAGE = """
Lender: Maple Bank
Mortgage number: ABCD-1234-5678
Outstanding mortgage balance at renewal: $480,000.00
Current interest rate: 4.19%
Renewal interest rate: 5.49%
Renewal term: 3 years
Remaining amortization period: 19 years 0 months
Maturity date: March 1, 2027
Payment amount: $3,378.66
Payment frequency: monthly
"""


def extraction(text=SAMPLE_PAGE, **kwargs):
    return extract_ocr_fields(
        [{"page_number": 1, "text": text, "mean_confidence": 0.92}],
        filename="renewal-ocr.txt",
        **kwargs,
    )


def test_extracts_core_mortgage_fields():
    result = extraction()
    assert result["provider"] == "deterministic-ocr-fields-v10"
    assert result["fields"]["balance"]["value"] == 480000.0
    assert result["fields"]["offered_rate"]["value"] == 5.49
    assert result["fields"]["current_rate"]["value"] == 4.19
    assert result["fields"]["term_months"]["value"] == 36
    assert result["fields"]["amortization_months"]["value"] == 228
    assert result["fields"]["maturity_date"]["value"] == "2027-03-01"
    assert result["fields"]["frequency"]["value"] == "monthly"
    assert result["fields"]["mortgage_reference"]["value"] == "****5678"
    assert result["review_status"] == "ready"
    assert result["missing_required"] == []


def test_mortgage_draft_contains_prefill_safe_fields():
    result = extraction()
    draft = result["mortgage_draft"]
    assert draft["balance"] == 480000.0
    assert draft["offered_rate"] == 5.49
    assert draft["term_months"] == 36
    assert draft["amortization_months"] == 228
    assert draft["maturity_date"] == "2027-03-01"
    assert "mortgage_reference" not in draft


def test_excerpts_are_redacted():
    result = extraction()
    reference = result["fields"]["mortgage_reference"]
    assert "ABCD-1234-5678" not in reference["excerpt"]
    assert "[account-ref]" in reference["excerpt"]


def test_redacts_common_identifiers():
    text = "email test@example.com phone 416-555-1212 SIN 123-456-789 account number ABCD123456"
    redacted = redact_sensitive_text(text)
    assert "test@example.com" not in redacted
    assert "416-555-1212" not in redacted
    assert "123-456-789" not in redacted
    assert "ABCD123456" not in redacted


def test_numeric_repair_handles_common_ocr_noise():
    assert repair_numeric_token("48O,OOO.OO") == "480000.00"
    assert repair_numeric_token("I234.5O") == "1234.50"
    assert parse_money("48O,OOO.OO").value == 480000.0
    assert parse_percent("5.O9").value == 5.09


@pytest.mark.parametrize(
    "raw,expected,warnings",
    [
        ("2027-03-01", "2027-03-01", ()),
        ("March 1, 2027", "2027-03-01", ()),
        ("03/01/2027", "2027-03-01", ("ambiguous_numeric_date",)),
        ("31/01/2027", "2027-01-31", ()),
    ],
)
def test_date_parser(raw, expected, warnings):
    parsed = parse_date_value(raw)
    assert parsed.value == expected
    for warning in warnings:
        assert warning in parsed.warnings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("monthly", "monthly"),
        ("semi monthly", "semi-monthly"),
        ("bi-weekly", "biweekly"),
        ("weekly", "weekly"),
    ],
)
def test_frequency_parser(raw, expected):
    assert parse_enum(raw, field_specs()["frequency"].allowed_values).value == expected


def test_conflicting_candidates_lower_confidence_and_warn():
    text = SAMPLE_PAGE + "\nRenewal interest rate: 5.79%\n"
    result = extraction(text)
    rate = result["fields"]["offered_rate"]
    assert rate["value"] in (5.49, 5.79)
    assert "conflicting_ocr_candidates" in rate["warnings"]
    assert "conflicting_candidates:offered_rate" in result["warnings"]
    assert result["review_status"] in ("blocked", "review_recommended")


def test_low_page_confidence_marks_review():
    result = extract_ocr_fields([{"text": SAMPLE_PAGE, "mean_confidence": 0.4}])
    assert result["fields"]["balance"]["confidence"] in ("medium", "low")
    assert "low_page_ocr_confidence" in result["fields"]["balance"]["warnings"]
    assert result["review_status"] in ("blocked", "review_recommended")


def test_missing_required_fields_block_prefill():
    result = extraction("Payment amount: $3000.00\nPayment frequency: monthly")
    assert result["review_status"] == "blocked"
    assert set(result["missing_required"]) == {
        "balance",
        "offered_rate",
        "amortization_months",
        "maturity_date",
    }
    summary = summarize_review_decision(result)
    assert not summary["can_prefill_mortgage_form"]


def test_manual_corrections_override_ocr_candidates():
    result = extract_ocr_fields(
        [{"text": "Balance: $480,000\nRenewal rate: 5.49%\nAmortization: 228 months"}],
        corrections={"maturity_date": "2027-03-01", "offered_rate": "4.99"},
    )
    assert result["fields"]["offered_rate"]["value"] == 4.99
    assert result["fields"]["offered_rate"]["source"] == "manual_review"
    assert result["fields"]["maturity_date"]["value"] == "2027-03-01"
    assert len(result["manual_corrections"]) == 2


def test_unknown_correction_rejected():
    with pytest.raises(OCRFieldError):
        extraction(corrections={"social_insurance_number": "123"})


def test_invalid_correction_rejected():
    with pytest.raises(OCRFieldError):
        extraction(corrections={"offered_rate": "not a rate"})


def test_min_confidence_filters_candidates_then_corrections_can_fill():
    result = extract_ocr_fields(
        [{"text": SAMPLE_PAGE, "mean_confidence": 0.6}],
        min_confidence=0.95,
        corrections={"balance": "480000.00", "offered_rate": "5.49", "amortization_months": 228, "maturity_date": "2027-03-01"},
    )
    assert result["fields"]["balance"]["source"] == "manual_review"
    assert result["review_status"] == "ready"


def test_prepare_pages_accepts_strings_dicts_and_dataclasses():
    pages = prepare_pages(["one", {"page": 2, "text": "two", "mean_confidence": 0.5}, OCRTextPage(3, "three")])
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert all(page.source_hash for page in pages)


def test_prepare_pages_limits():
    with pytest.raises(OCRFieldError):
        prepare_pages([])
    with pytest.raises(OCRFieldError):
        prepare_pages(["x"] * 17)
    with pytest.raises(OCRFieldError):
        prepare_pages([{"page": 1, "text": "x", "mean_confidence": 2}])
    with pytest.raises(OCRFieldError):
        prepare_pages([{"page": 1, "text": "x" * 25001}])


def test_document_metrics_do_not_return_raw_text():
    pages = prepare_pages([SAMPLE_PAGE])
    metrics = document_metrics(pages)
    assert metrics["pages"] == 1
    assert metrics["word_count"] > 20
    assert "Maple Bank" not in str(metrics)


def test_page_preview_is_redacted_and_bounded():
    result = extraction()
    preview = result["preview"][0]["preview"]
    assert len(preview) < 700
    assert "ABCD-1234-5678" not in preview
    assert result["preview"][0]["text_sha256"]


def test_find_candidates_groups_alternatives():
    pages = prepare_pages([SAMPLE_PAGE + "\nBalance: $481,000.00"])
    grouped = find_candidates(pages)
    assert "balance" in grouped
    assert len(grouped["balance"]) >= 2


def test_flatten_preserves_table_style_text():
    text = "Outstanding mortgage balance\n$480,000.00\nRenewal interest rate\n5.49%"
    flattened = flatten_ocr_text(text)
    assert "\n" not in flattened
    assert "480,000.00" in flattened


def test_review_packet_status_helpers():
    result = extraction()
    assert review_status(result["review_packet"]) == "ready"
    summary = summarize_review_decision(result)
    assert summary["status"] == "ready"
    assert summary["field_count"] >= 8


def test_confidence_labels_are_stable():
    assert confidence_label(0.9) == "high"
    assert confidence_label(0.7) == "medium"
    assert confidence_label(0.2) == "low"


def test_apply_corrections_returns_audit():
    original = extraction()
    fields = {key: value for key, value in original["fields"].items()}
    # Convert public dictionaries back through the normal public API by using extract again.
    corrected = extract_ocr_fields([SAMPLE_PAGE], corrections={"payment_amount": "3122.52"})
    assert corrected["fields"]["payment_amount"]["source"] == "manual_review"
    assert corrected["manual_corrections"][0]["field"] == "payment_amount"
    assert fields["payment_amount"]["value"] == 3378.66


def test_money_and_percent_reject_out_of_range():
    assert parse_money("-1") is None
    assert parse_money("100000001") is None
    assert parse_percent("31") is None

