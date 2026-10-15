import pytest

from renewal.ocr.document_understanding import (
    classify_document,
    consistency_checks,
    detect_clauses,
    detect_sections,
    extract_fine_details,
    understand_ocr_document,
)
from renewal.ocr.engine_registry import (
    OCREngineRegistryError,
    list_engine_profiles,
    recommend_ocr_engines,
)
from renewal.ocr.fields import extract_ocr_fields, prepare_pages
from renewal.ocr.mortgage_terms import (
    contract_discount_math,
    explain_extracted_terms,
    glossary_public,
    payment_formula_explanation,
    timeline_explanation,
)


SAMPLE_CONTRACT = """
Maple Bank Mortgage Renewal Agreement
Mortgage number: ABCD-1234-5678
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Current interest rate: 4.39%
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Renewal term: 60 months
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Payment amount: $3,285.00
Payment frequency: monthly
Prepayment privilege: You may prepay up to 20% of the original principal each year.
If you prepay early, the penalty may be the greater of three months interest or
the interest rate differential (IRD). Offer expires: 2027-02-15.
Property taxes are not collected with this payment.
"""


def pages(text=SAMPLE_CONTRACT):
    return [{"page_number": 1, "text": text, "mean_confidence": 0.94}]


def understanding(text=SAMPLE_CONTRACT):
    return understand_ocr_document(pages(text), filename="contract-renewal.txt")


def by_check(result, key):
    return next(item for item in result["consistency_checks"] if item["check"] == key)


def by_clause(result, key):
    return next(item for item in result["clauses"] if item["clause"] == key)


def test_understands_contract_rate_discount_ird_and_mortgage_date():
    result = understanding()
    fields = result["extraction"]["fields"]
    assert result["provider"] == "deterministic-document-understanding-v11"
    assert result["classification"]["type"] == "renewal_offer"
    assert fields["contract_rate"]["value"] == 4.39
    assert fields["posted_rate"]["value"] == 5.69
    assert fields["contract_discount"]["value"] == 1.3
    assert fields["mortgage_start_date"]["value"] == "2022-03-01"
    assert fields["term_months"]["value"] == 60
    assert by_clause(result, "interest_rate_differential")["status"] == "found"
    assert by_clause(result, "contract_discount_language")["status"] == "found"
    assert by_clause(result, "mortgage_date_language")["status"] == "found"
    assert by_check(result, "contract_rate_discount_math")["status"] == "pass"
    assert by_check(result, "mortgage_date_term_maturity_sequence")["status"] == "pass"
    assert "ABCD-1234-5678" not in str(result)


def test_canadian_terms_explain_extracted_values_and_formulas():
    result = understanding()
    terms = result["canadian_mortgage_terms"]
    labels = {item["key"]: item for item in terms["present_terms"]}
    assert labels["contract_rate"]["extracted_value"] == "4.39"
    assert labels["contract_discount"]["extracted_value"] == "1.3"
    assert terms["calculations"]["contract_discount"]["status"] == "matches"
    assert terms["calculations"]["contract_discount"]["formula"] == "posted_rate - contract_rate = implied_discount"
    assert terms["calculations"]["term_timeline"]["months_between"] == 60
    assert terms["calculations"]["term_timeline"]["status"] == "matches"
    payment = terms["calculations"]["payment_estimate"]
    assert payment["frequency"] == "monthly"
    assert payment["periods_per_year"] == 12
    assert payment["formula_note"].startswith("For fixed rates")


def test_sections_and_fine_details_are_source_linked_and_redacted():
    prepared = prepare_pages(pages())
    sections = detect_sections(prepared)
    details = extract_fine_details(prepared)
    section_names = {item["section"] for item in sections}
    assert {"rates", "payments", "term", "maturity", "prepayment", "penalty"} & section_names
    assert any(item["kind"] == "percent" and item["value"] == 5.69 for item in details)
    assert any(item["kind"] == "duration" and item["raw_display"].startswith("60") for item in details)
    assert all("ABCD-1234-5678" not in item["excerpt"] for item in details)


def test_classification_scores_unknown_documents_low():
    prepared = prepare_pages([{"text": "Hello this page has almost no mortgage vocabulary."}])
    result = classify_document(prepared)
    assert result["type"] == "unknown"
    assert result["confidence"] == "low"


def test_consistency_flags_contract_discount_mismatch():
    text = SAMPLE_CONTRACT.replace("Contract discount: 1.30%", "Contract discount: 0.30%")
    result = understanding(text)
    check = by_check(result, "contract_rate_discount_math")
    assert check["status"] == "review"
    assert check["contract_discount"] == 0.3
    assert "does not line up" in check["detail"]


def test_missing_mortgage_date_generates_review_question():
    text = SAMPLE_CONTRACT.replace("Mortgage date: 2022-03-01", "")
    result = understanding(text)
    assert "mortgage_start_date" in result["canadian_mortgage_terms"]["missing_term_context"]
    topics = {item["topic"] for item in result["review_questions"]}
    assert "mortgage_date_language" in topics


def test_payment_formula_uses_canadian_fixed_rate_conversion():
    calc = payment_formula_explanation(480000, 5.49, 240, "monthly", "fixed")
    assert calc["periods_per_year"] == 12
    assert calc["periodic_rate"] > 0
    assert calc["estimated_payment"] > 3200
    assert "semi-annually" in calc["formula_note"]


def test_contract_discount_and_timeline_helpers():
    discount = contract_discount_math(5.69, 4.39, 1.30)
    assert discount["status"] == "matches"
    assert discount["implied_discount"] == 1.3
    timeline = timeline_explanation("2022-03-01", "2027-03-01", 60)
    assert timeline["status"] == "matches"
    assert timeline["months_between"] == 60


def test_glossary_contains_core_canadian_terms():
    glossary = glossary_public()
    keys = {item["key"] for item in glossary["terms"]}
    assert {"contract_rate", "posted_rate", "contract_discount", "interest_rate_differential"} <= keys
    assert "semi-annually" in glossary["calculation_note"]


def test_engine_registry_recommends_tesseract_for_local_simple_ocr():
    result = recommend_ocr_engines(
        {
            "document_type": "image",
            "privacy_mode": "local_only",
            "setup_budget": "low",
            "output_goal": "fields",
            "languages": ["eng"],
        }
    )
    assert result["primary"]["engine"] == "tesseract"
    assert result["field_review_required"] is True


def test_engine_registry_prefers_layout_engine_for_tables():
    result = recommend_ocr_engines(
        {
            "document_type": "mixed_pdf",
            "privacy_mode": "local_only",
            "setup_budget": "high",
            "output_goal": "tables",
            "needs_layout": True,
            "needs_tables": True,
            "allow_gpu": True,
            "languages": ["iso:en"],
        }
    )
    assert result["primary"]["engine"] in {"docling", "paddleocr"}
    assert result["primary"]["recommended"] is True


def test_engine_registry_rejects_bad_options():
    with pytest.raises(OCREngineRegistryError):
        recommend_ocr_engines({"document_type": "spreadsheet"})
    with pytest.raises(OCREngineRegistryError):
        recommend_ocr_engines({"languages": ["eng"] * 13})


def test_engine_registry_lists_latest_public_signals():
    result = list_engine_profiles()
    engines = {item["key"]: item for item in result["engines"]}
    assert "Tesseract 5" in engines["tesseract"]["latest_signal"]
    assert "PP-OCRv6" in engines["paddleocr"]["latest_signal"]
    assert "RapidOCR" in engines["docling"]["latest_signal"]


def test_explain_extracted_terms_handles_partial_extraction():
    extraction = extract_ocr_fields(pages("Contract rate: 4.39%\nPosted rate: 5.69%"))
    terms = explain_extracted_terms(extraction)
    assert terms["calculations"]["contract_discount"]["status"] == "inferred_only"
    assert "contract_discount" in terms["missing_term_context"]
