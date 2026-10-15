from datetime import date, datetime

import pytest

from renewal.ocr.document_semantic_auditor_v16 import (
    add_calendar_months,
    create_document_semantic_audit,
)
from renewal.ocr.semantic_evidence_v16 import DocumentSemanticAuditError


CONTRACT = """Original mortgage
Mortgage date: 2022-03-01
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Term: 5 years
Maturity date: 2027-03-01
Renewal offer
Term start date: 2027-03-01
Renewal rate: 5.49%
Term: 36 months
Maturity date: 2030-03-01
Balance: $480,000.00
Remaining amortization: 20 years
Payment amount: $3,100.00
Payment frequency: monthly
Offer expires: 2027-02-15
The penalty is the greater of three months interest or the interest rate differential.
"""


def audit(text=CONTRACT, **options):
    return create_document_semantic_audit(
        [{"page_number": 1, "text": text, "mean_confidence": 0.95}],
        as_of=options.pop("as_of", date(2026, 10, 14)), **options,
    )


def check(result, key):
    return next(item for item in result["checks"] if item["id"] == key)


def test_complete_document_has_scoped_rate_and_calendar_checks():
    result = audit()
    assert result["provider"] == "mortgage-document-semantic-auditor-v16"
    assert check(result, "original:rate-discount")["status"] == "consistent"
    assert check(result, "original:term-calendar")["status"] == "consistent"
    assert check(result, "renewal:term-calendar")["status"] == "consistent"
    assert check(result, "renewal:term-amortization")["output"]["months_after_term"] == 204
    assert result["summary"]["scopes"] == ["original", "renewal"]
    assert result["summary"]["status"] == "review_required"


def test_discount_calculation_reports_percentage_points():
    item = check(audit(), "original:rate-discount")
    assert item["output"] == {"calculated_discount_points": 1.3, "residual_points": 0.0}
    assert "percentage points" in item["formula"]
    assert item["inputs"]["posted_rate"] == 5.69
    assert len(item["evidence"]) == 3


def test_inconsistent_discount_is_reported_with_signed_residual():
    result = audit(CONTRACT.replace("Contract discount: 1.30%", "Contract discount: 1.00%"))
    item = check(result, "original:rate-discount")
    assert item["status"] == "conflict"
    assert item["output"]["residual_points"] == 0.3
    assert result["summary"]["status"] == "conflict"
    assert result["review_prompts"][0]["priority"] == "high"


def test_missing_original_discount_cannot_be_filled_with_renewal_discount():
    text = "Original contract rate: 4.39%\nOriginal posted rate: 5.69%\nRenewal contract discount: 1.30%"
    result = audit(text)
    original = check(result, "original:rate-discount")
    assert original["status"] == "incomplete"
    assert original["inputs"]["contract_discount"] is None
    assert original["output"] is None


def test_rate_change_is_distinct_from_ird_or_original_discount():
    item = check(audit(), "document:renewal-rate-change")
    assert item["status"] == "observed"
    assert item["output"]["change_percentage_points"] == 1.1
    assert item["output"]["change_basis_points"] == 110
    assert "not a contract discount" in item["detail"]


def test_conflicting_contract_rates_block_discount_calculation():
    result = audit(CONTRACT + "\nOriginal contract rate: 4.89%")
    assert check(result, "original:fact-contract_rate")["status"] == "conflict"
    assert check(result, "original:rate-discount")["status"] == "incomplete"
    assert result["facts"]["original.contract_rate"]["value"] is None


def test_negative_discount_is_a_conflict_even_if_other_rates_are_valid():
    text = "Original mortgage\nPosted rate: 4.00%\nContract rate: 5.00%\nContract discount: 0%"
    item = check(audit(text), "original:rate-discount")
    assert item["status"] == "conflict"
    assert item["output"]["calculated_discount_points"] == -1


def test_ocr_repaired_rate_does_not_feed_a_confirmed_calculation():
    result = audit(CONTRACT.replace("Contract rate: 4.39%", "Contract rate: 4.3O%"))
    assert check(result, "original:fact-contract_rate")["status"] == "review"
    assert check(result, "original:rate-discount")["status"] == "incomplete"


@pytest.mark.parametrize("start,months,expected", [
    (date(2024, 1, 31), 1, date(2024, 2, 29)),
    (date(2023, 1, 31), 1, date(2023, 2, 28)),
    (date(2024, 2, 29), 12, date(2025, 2, 28)),
    (date(2022, 3, 1), 60, date(2027, 3, 1)),
    (date(2026, 12, 31), 2, date(2027, 2, 28)),
    (date(2026, 10, 14), 0, date(2026, 10, 14)),
])
def test_calendar_month_addition_preserves_month_end(start, months, expected):
    assert add_calendar_months(start, months) == expected


@pytest.mark.parametrize("months", [-1, 601, 1.5, True])
def test_calendar_month_addition_rejects_invalid_lengths(months):
    with pytest.raises(DocumentSemanticAuditError):
        add_calendar_months(date(2026, 1, 1), months)


def test_calendar_overflow_is_a_domain_error():
    with pytest.raises(DocumentSemanticAuditError):
        add_calendar_months(date(9999, 12, 31), 1)


def test_maturity_difference_uses_calendar_days():
    text = CONTRACT.replace("Maturity date: 2030-03-01", "Maturity date: 2030-03-03")
    item = check(audit(text), "renewal:term-calendar")
    assert item["status"] == "conflict"
    assert item["output"] == {"expected_maturity": "2030-03-01", "difference_days": 2}


def test_original_funding_date_is_not_used_for_renewal_term_start():
    text = CONTRACT.replace("Term start date: 2027-03-01\n", "")
    item = check(audit(text), "renewal:term-calendar")
    assert item["status"] == "incomplete"
    assert item["inputs"]["term_start_date"] is None
    assert "mortgage_start_date" not in item["inputs"]


def test_ambiguous_maturity_does_not_support_timeline_arithmetic():
    result = audit(CONTRACT.replace("Maturity date: 2030-03-01", "Maturity date: 03/04/2030"))
    assert check(result, "renewal:term-calendar")["status"] == "incomplete"
    assert not any(item["id"] == "renewal:maturity-distance" for item in result["checks"])
    assert check(result, "renewal:fact-maturity_date")["status"] == "review"


def test_future_and_past_maturities_are_measured_from_explicit_audit_date():
    result = audit(as_of=date(2027, 3, 2))
    original = check(result, "original:maturity-distance")
    renewal = check(result, "renewal:maturity-distance")
    assert original["output"] == {"days_remaining": -1, "has_matured": True}
    assert renewal["output"]["days_remaining"] > 0
    assert result["as_of"] == "2027-03-02"


def test_amortization_shorter_than_term_requires_review():
    text = CONTRACT.replace("Remaining amortization: 20 years", "Remaining amortization: 24 months")
    item = check(audit(text), "renewal:term-amortization")
    assert item["status"] == "review"
    assert item["output"]["months_after_term"] == -12


def test_offer_expiry_is_separate_from_term_start_and_maturity():
    item = check(audit(), "renewal:offer-window")
    assert item["output"]["days_between_expiry_and_start"] == 14
    assert item["inputs"]["offer_expiry_date"] == "2027-02-15"
    assert "acceptance deadline" in item["detail"]


@pytest.mark.parametrize("text,assertion", [
    ("Interest rate differential applies.", "mentioned"),
    ("Intrest rate differental applies.", "mentioned"),
    ("Interest rate diferencial applies.", "mentioned"),
    ("IRD applies.", "mentioned"),
    ("Interest rate differential does not apply.", "negated"),
    ("No interest rate differential applies.", "negated"),
    ("If discharged early, interest rate differential applies.", "conditional"),
    ("Interest rate differential does not apply if the mortgage is open.", "conditional"),
    ("Illustrative interest rate differential is $12,000.", "example"),
])
def test_ird_wording_keeps_polarity_and_conditions(text, assertion):
    result = audit(text)
    clauses = [item for item in result["clauses"] if item["topic"] == "ird"]
    assert len(clauses) == 1
    assert clauses[0]["assertion"] == assertion
    assert clauses[0]["page"] == 1
    assert clauses[0]["line"] == 1


def test_negated_ird_does_not_waive_every_discharge_fee():
    result = audit("Interest rate differential does not apply.")
    item = check(result, "document:ird-language")
    assert item["status"] == "observed"
    assert "does not establish" in item["detail"]
    assert not any(item["id"] == "document:ird-inputs" for item in result["checks"])


def test_clause_negation_does_not_leak_to_another_sentence():
    result = audit("No prepayment penalty applies. Interest rate differential applies.")
    clause = next(item for item in result["clauses"] if item["topic"] == "ird")
    assert clause["assertion"] == "mentioned"


def test_conflicting_ird_statements_trigger_high_priority_review():
    result = audit("Interest rate differential applies. Interest rate differential does not apply.")
    assert check(result, "document:ird-language")["status"] == "conflict"
    prompt = next(item for item in result["review_prompts"] if item["check_id"] == "document:ird-language")
    assert prompt["priority"] == "high"
    assert prompt["pages"] == [1]


def test_ird_only_in_example_cannot_establish_contract_penalty():
    item = check(audit("Example interest rate differential is $12,000."), "document:ird-language")
    assert item["status"] == "review"
    assert "illustrative" in item["detail"]


def test_missing_ird_clause_never_claims_a_zero_penalty():
    result = audit("Renewal rate: 5.49%")
    item = check(result, "document:ird-language")
    assert item["status"] == "incomplete"
    assert item["output"] is None
    assert "no penalty" in item["detail"]


def test_ird_needs_payout_comparison_rate_not_renewal_offer():
    result = audit()
    item = check(result, "document:ird-inputs")
    assert "payout.comparison_rate" in item["output"]["missing_fields"]
    assert result["facts"]["renewal.offered_rate"]["value"] == 5.49


def test_even_complete_ird_inputs_require_the_lender_formula():
    result = audit(CONTRACT + "\nPayout statement\nComparison rate: 3.49%\nPayout date: 2026-10-20")
    item = check(result, "document:ird-inputs")
    assert item["output"]["missing_fields"] == []
    assert item["status"] == "review"
    assert item["output"]["lender_formula_required"] is True


def test_payment_addons_and_automatic_renewal_have_distinct_prompts():
    result = audit(CONTRACT + "\nProperty tax is included in the payment.\n"
                   "Insurance is added to the payment.\nThe contract renews automatically.")
    assert check(result, "document:tax_in_payment")["status"] == "review"
    assert check(result, "document:insurance_in_payment")["status"] == "review"
    assert check(result, "document:automatic_renewal")["status"] == "review"
    assert "principal and interest" in check(result, "document:tax_in_payment")["detail"]


def test_every_public_evidence_reference_resolves_to_a_ledger_item():
    result = audit()
    ids = {item["id"] for item in result["mentions"] + result["clauses"]}
    assert len(ids) == len(result["mentions"]) + len(result["clauses"])
    for item in result["checks"] + result["review_prompts"]:
        assert set(item["evidence"]) <= ids
    assert result["summary"]["mention_count"] == len(result["mentions"])
    assert result["summary"]["fact_count"] == len(result["facts"])


def test_raw_page_text_is_not_returned_or_stored():
    result = audit(CONTRACT + "\nUnrelated personal sentence that is not a mortgage field.")
    assert result["raw_ocr_stored"] is False
    assert "text" not in result["pages"][0]
    assert "Unrelated personal sentence" not in str(result)


def test_public_filename_drops_directory_components():
    result = audit(filename="C:\\Private\\Borrower\\mortgage.pdf")
    assert result["filename"] == "mortgage.pdf"


def test_source_references_are_primary_fcac_pages():
    result = audit()
    assert len(result["sources"]) == 3
    assert all(item["url"].startswith("https://www.canada.ca/") for item in result["sources"])


def test_audit_is_repeatable_with_fixed_date_and_input():
    assert audit() == audit()


@pytest.mark.parametrize("as_of", ["2026-10-14", datetime(2026, 10, 14), 42])
def test_invalid_audit_dates_raise_domain_error(as_of):
    with pytest.raises(DocumentSemanticAuditError):
        audit(as_of=as_of)


def test_large_clause_ledgers_are_bounded():
    with pytest.raises(DocumentSemanticAuditError, match="clause"):
        audit("IRD applies.\n" * 401)
