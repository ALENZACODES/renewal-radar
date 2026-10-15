from dataclasses import replace

import pytest

from renewal.ocr.fields import OCRTextPage
from renewal.ocr.semantic_evidence_v16 import (
    DocumentSemanticAuditError,
    apply_semantic_corrections,
    canonical_text,
    extract_semantic_mentions,
    parse_semantic_date,
    resolve_semantic_facts,
    validate_pages,
)


def mentions(text, confidence=None):
    return extract_semantic_mentions(validate_pages([
        {"page_number": 1, "text": text, "mean_confidence": confidence},
    ]))


def facts(text, confidence=None, threshold=0):
    return resolve_semantic_facts(mentions(text, confidence), threshold)


def test_explicit_original_and_renewal_rates_remain_separate():
    result = facts("Original contract rate: 4.39%\nRenewal contract rate: 5.49%")
    assert result["original.contract_rate"]["value"] == 4.39
    assert result["renewal.contract_rate"]["value"] == 5.49
    assert all(item["status"] == "resolved" for item in result.values())


def test_headings_assign_generic_fields_to_each_term():
    result = facts("Original mortgage\nContract rate: 4.39%\nTerm: 5 years\n"
                   "Renewal offer\nContract rate: 5.49%\nTerm: 3 years")
    assert result["original.term_months"]["value"] == 60
    assert result["renewal.term_months"]["value"] == 36
    assert result["renewal.contract_rate"]["value"] == 5.49


def test_heading_context_does_not_leak_across_pages():
    pages = validate_pages([
        {"page_number": 1, "text": "Original mortgage\nContract rate: 4.39%"},
        {"page_number": 2, "text": "Contract rate: 5.49%"},
    ])
    result = resolve_semantic_facts(extract_semantic_mentions(pages))
    assert result["original.contract_rate"]["value"] == 4.39
    assert result["unspecified.contract_rate"]["value"] == 5.49


def test_explicit_renewal_label_overrides_original_heading():
    result = facts("Original mortgage\nRenewal rate: 5.49%")
    assert result["renewal.offered_rate"]["value"] == 5.49
    assert "original.offered_rate" not in result


def test_spelling_repairs_only_change_labels():
    text = "Contract intrest rate: 4.39%\nIntrest rate differental applies"
    assert canonical_text(text).startswith("Contract interest rate: 4.39%")
    assert "interest rate differential" in canonical_text(text)
    result = facts(text)
    assert result["unspecified.contract_rate"]["value"] == 4.39


def test_renewal_offer_rate_label_matches_the_bundled_sample_letter():
    result = facts("Renewal Offer: 5.49% fixed")
    assert result["renewal.offered_rate"]["value"] == 5.49


def test_renewal_date_is_not_relabelled_as_original_maturity_or_start():
    result = facts("Renewal Date: 2027-03-01")
    assert result["renewal.renewal_date"]["value"] == "2027-03-01"
    assert "original.maturity_date" not in result
    assert "renewal.term_start_date" not in result


def test_ligature_and_nonbreaking_space_labels_are_readable():
    result = facts("Contract\u00a0rate: 4.39%\nPayment frequency: accelerated\u2013biweekly")
    assert result["unspecified.contract_rate"]["value"] == 4.39
    assert result["unspecified.frequency"]["value"] == "accelerated-biweekly"


def test_table_label_may_read_its_immediately_following_value():
    ledger = mentions("Original mortgage\nContract rate:\n4.39%\nPosted rate:\n5.69%")
    assert len(ledger) == 2
    assert ledger[0].value == 4.39
    assert ledger[0].line == 2
    assert "4.39%" in ledger[0].excerpt


def test_table_label_does_not_search_past_an_unrelated_line():
    ledger = mentions("Contract rate:\nPlease contact your lender\n4.39%")
    assert ledger == []


def test_two_rates_in_same_sentence_use_local_labels():
    result = facts("Original contract rate: 4.39%; Renewal contract rate: 5.49%")
    assert result["original.contract_rate"]["value"] == 4.39
    assert result["renewal.contract_rate"]["value"] == 5.49


@pytest.mark.parametrize("label,value,key,expected", [
    ("Contract rate", "4.39%", "contract_rate", 4.39),
    ("Contractual interest rate", "4.39 percent", "contract_rate", 4.39),
    ("Registered rate", "4.39%", "contract_rate", 4.39),
    ("Posted rate", "5.69%", "posted_rate", 5.69),
    ("Contract discount", "130 bps", "contract_discount", 1.3),
    ("Rate discount", "130 basis points", "contract_discount", 1.3),
    ("Discount from posted rate", "1.30 percentage points", "contract_discount", 1.3),
    ("Outstanding mortgage balance", "$480,000.00", "balance", 480000),
    ("Payment amount", "$3,120.75", "payment_amount", 3120.75),
    ("Term", "5 years", "term_months", 60),
    ("Amortization", "19 years 6 months", "amortization_months", 234),
    ("Amortisation period", "240 months", "amortization_months", 240),
    ("Payment frequency", "bi-weekly", "frequency", "biweekly"),
    ("Frequency", "semi monthly", "frequency", "semi-monthly"),
])
def test_supported_field_units(label, value, key, expected):
    result = facts(f"{label}: {value}")
    assert result[f"unspecified.{key}"]["value"] == expected


def test_numeric_ocr_repairs_are_retained_for_review():
    result = facts("Original contract rate: 4.3O%")
    fact = result["original.contract_rate"]
    assert fact["value"] == 4.3
    assert fact["status"] == "review"
    assert mentions("Original contract rate: 4.3O%")[0].warnings == ("ocr_numeric_repair",)


def test_comma_decimal_rate_is_ambiguous_instead_of_becoming_439_percent():
    ledger = mentions("Contract rate: 4,39%")
    assert ledger[0].value is None
    assert "ambiguous_decimal_separator" in ledger[0].warnings
    assert resolve_semantic_facts(ledger)["unspecified.contract_rate"]["status"] == "unreadable"


@pytest.mark.parametrize("raw,expected", [
    ("480,000.00", 480000), ("480 000.00", 480000),
    ("480000.00", 480000), ("3,100.75", 3100.75),
])
def test_canadian_money_grouping_preserves_amount(raw, expected):
    assert facts(f"Balance: ${raw}")["unspecified.balance"]["value"] == expected


@pytest.mark.parametrize("raw", ["480000,00", "480.000,00", "48,00", "480.000.00"])
def test_ambiguous_money_grouping_never_changes_the_magnitude(raw):
    ledger = mentions(f"Balance: ${raw}")
    assert ledger[0].value is None
    assert ledger[0].warnings == ("ambiguous_money_separator",)


def test_multiple_rate_decimal_separators_are_not_silently_joined():
    ledger = mentions("Contract rate: 4.3.9%")
    assert ledger[0].value is None
    assert ledger[0].warnings == ("invalid_decimal_separator",)


@pytest.mark.parametrize("text", [
    "Contract rate: 31%", "Balance: $0", "Term: 0 months",
    "Amortization: 601 months", "Term: 2 years 12 months",
])
def test_invalid_numeric_ranges_remain_unreadable_evidence(text):
    ledger = mentions(text)
    assert len(ledger) == 1
    assert ledger[0].value is None
    assert ledger[0].warnings


def test_conflicting_values_are_not_selected_by_confidence():
    ledger = extract_semantic_mentions(validate_pages([
        {"page_number": 1, "text": "Original contract rate: 4.39%", "mean_confidence": 0.99},
        {"page_number": 2, "text": "Original contract rate: 4.89%", "mean_confidence": 0.8},
    ]))
    result = resolve_semantic_facts(ledger)
    fact = result["original.contract_rate"]
    assert fact["status"] == "conflict"
    assert fact["value"] is None
    assert fact["candidate_values"] == ["4.39", "4.89"]
    assert len(fact["evidence"]) == 2


def test_repeated_agreeing_evidence_remains_source_linked():
    ledger = mentions("Original contract rate: 4.39%\nOriginal contract rate: 4.39%")
    fact = resolve_semantic_facts(ledger)["original.contract_rate"]
    assert fact["status"] == "resolved"
    assert len(fact["eligible_evidence"]) == 2
    assert ledger[0].id != ledger[1].id


def test_minimum_confidence_excludes_unknown_and_low_scores():
    assert facts("Contract rate: 4.39%", None, 0.8)["unspecified.contract_rate"]["status"] == "unreadable"
    assert facts("Contract rate: 4.39%", 0.79, 0.8)["unspecified.contract_rate"]["value"] is None
    assert facts("Contract rate: 4.39%", 0.8, 0.8)["unspecified.contract_rate"]["value"] == 4.39


@pytest.mark.parametrize("raw,expected", [
    ("2022-03-01", "2022-03-01"), ("2022/3/1", "2022-03-01"),
    ("March 1, 2022", "2022-03-01"), ("Mar 1 2022", "2022-03-01"),
    ("1 March 2022", "2022-03-01"), ("13/03/2022", "2022-03-13"),
    ("03/13/2022", "2022-03-13"), ("03/03/2022", "2022-03-03"),
])
def test_date_formats_with_one_interpretation(raw, expected):
    value, warnings = parse_semantic_date(raw)
    assert value == expected
    assert warnings == ()


@pytest.mark.parametrize("raw", ["03/04/2022", "01/12/2026"])
def test_ambiguous_slash_dates_do_not_guess_month_order(raw):
    value, warnings = parse_semantic_date(raw)
    assert value is None
    assert warnings == ("ambiguous_date_order",)


@pytest.mark.parametrize("raw", ["2023-02-29", "2022-13-01", "31/02/2022", "nonsense"])
def test_invalid_dates_are_rejected(raw):
    value, warnings = parse_semantic_date(raw)
    assert value is None
    assert warnings == ("invalid_date",)


def test_date_mentions_keep_ambiguous_value_and_original_location():
    ledger = mentions("Mortgage date: 03/04/2022")
    assert ledger[0].scope == "original"
    assert ledger[0].raw_value == "03/04/2022"
    assert ledger[0].page == 1
    assert ledger[0].line == 1
    assert ledger[0].value is None


def test_review_correction_resolves_conflict_without_deleting_evidence():
    ledger = mentions("Original contract rate: 4.39%\nOriginal contract rate: 4.89%")
    corrected = apply_semantic_corrections(ledger, {"original.contract_rate": 4.39})
    fact = resolve_semantic_facts(corrected)["original.contract_rate"]
    assert len(corrected) == 3
    assert all("superseded_by_reviewer" in item.warnings for item in corrected[:2])
    assert fact["value"] == 4.39
    assert fact["status"] == "resolved"
    assert fact["source"] == "reviewer"
    assert len(fact["evidence"]) == 3


def test_correction_scope_does_not_override_other_term():
    ledger = mentions("Original contract rate: 4.39%\nRenewal contract rate: 5.49%")
    corrected = apply_semantic_corrections(ledger, {"renewal.contract_rate": 5.19})
    result = resolve_semantic_facts(corrected)
    assert result["original.contract_rate"]["value"] == 4.39
    assert result["renewal.contract_rate"]["value"] == 5.19
    assert ledger[0].warnings == ()
    assert ledger[1].warnings == ()


def test_manual_correction_can_supply_missing_scoped_fact():
    corrected = apply_semantic_corrections([], {"renewal.term_months": 36})
    item = corrected[0]
    assert item.value == 36
    assert item.page is None
    assert item.line is None
    assert item.source_hash is None
    assert item.source == "reviewer"


def test_manual_iso_date_can_resolve_ambiguous_ocr_date():
    ledger = mentions("Mortgage date: 03/04/2022")
    corrected = apply_semantic_corrections(ledger, {"original.mortgage_start_date": "2022-04-03"})
    result = resolve_semantic_facts(corrected)
    assert result["original.mortgage_start_date"]["value"] == "2022-04-03"


@pytest.mark.parametrize("correction", [
    {"contract_rate": 4.39}, {"other.contract_rate": 4.39},
    {"original.unknown": 4.39}, {"original.contract_rate": True},
    {"original.contract_rate": float("nan")}, {"original.contract_rate": 31},
    {"original.mortgage_start_date": "03/04/2022"},
    {"original.contract_rate": "4.3O"}, {"original.term_months": 0},
    {"original.term_months": 36.5}, {"renewal.frequency": "daily"},
])
def test_invalid_corrections_raise_domain_error(correction):
    with pytest.raises(DocumentSemanticAuditError):
        apply_semantic_corrections([], correction)


def test_corrections_have_bounded_count_and_value_length():
    with pytest.raises(DocumentSemanticAuditError):
        apply_semantic_corrections([], {f"original.field{i}": 1 for i in range(21)})
    with pytest.raises(DocumentSemanticAuditError):
        apply_semantic_corrections([], {"renewal.frequency": "x" * 101})


def test_evidence_ids_are_stable_and_do_not_include_raw_text():
    first = mentions("Original contract rate: 4.39%")
    second = mentions("Original contract rate: 4.39%")
    assert first[0].id == second[0].id
    assert "4.39" not in first[0].id
    assert len(first[0].source_hash) == 64


def test_excerpts_redact_contact_and_account_information():
    ledger = mentions("Account number: 123456789; person@example.com; Contract rate: 4.39%")
    assert "person@example.com" not in ledger[0].excerpt
    assert "123456789" not in ledger[0].excerpt
    assert "4.39%" in ledger[0].excerpt


def test_pages_are_sorted_for_stable_document_order():
    result = validate_pages([
        {"page_number": 3, "text": "Contract rate: 4.39%"},
        {"page_number": 1, "text": "Mortgage date: 2022-03-01"},
    ])
    assert [page.page_number for page in result] == [1, 3]


@pytest.mark.parametrize("pages", [
    [], [""], [{"text": None}], [{"text": 42}], [{"text": "a", "page_number": True}],
    [{"text": "a", "page_number": 1.5}], [{"text": "a", "page_number": 201}],
    [{"text": "a", "mean_confidence": -1}], [{"text": "a", "mean_confidence": float("inf")}],
    [{"text": "a", "mean_confidence": float("nan")}], [42], ["x" * 25001],
])
def test_invalid_page_inputs_raise_domain_error(pages):
    with pytest.raises(DocumentSemanticAuditError):
        validate_pages(pages)


def test_duplicate_page_numbers_are_rejected():
    with pytest.raises(DocumentSemanticAuditError, match="Duplicate"):
        validate_pages([{"page_number": 1, "text": "a"}, {"page_number": 1, "text": "b"}])


def test_limits_apply_to_page_objects_as_well_as_dictionaries():
    with pytest.raises(DocumentSemanticAuditError):
        validate_pages([OCRTextPage(1, "x" * 25001)])
    with pytest.raises(DocumentSemanticAuditError):
        validate_pages([OCRTextPage(1, "x", float("nan"))])
    with pytest.raises(DocumentSemanticAuditError):
        validate_pages(["x"] * 17)


def test_excess_line_and_mention_counts_are_rejected():
    with pytest.raises(DocumentSemanticAuditError, match="lines"):
        validate_pages(["x\n" * 1201])
    prepared = validate_pages(["Original contract rate: 4.39%\n" * 401])
    with pytest.raises(DocumentSemanticAuditError, match="mentions"):
        extract_semantic_mentions(prepared)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_confidence_threshold_is_rejected(threshold):
    with pytest.raises(DocumentSemanticAuditError):
        resolve_semantic_facts([], threshold)


def test_correction_does_not_mutate_caller_evidence():
    original = mentions("Original contract rate: 4.39%")
    unchanged = replace(original[0])
    apply_semantic_corrections(original, {"original.contract_rate": 4.2})
    assert original[0] == unchanged
