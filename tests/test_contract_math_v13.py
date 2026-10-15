from datetime import date

import pytest

from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.contract_math_v13 import (
    ContractMathAuditError,
    annual_interest_amount,
    build_contract_math_audit_from_brief,
    field_dependency_map,
    formula_walkthroughs,
    months_between,
    penalty_scenarios,
    posted_discount_comparison_rate,
    remaining_months_until_maturity,
    renewal_disclosure_timeline,
    simple_ird_amount,
    term_months_from_dates,
    three_month_interest_amount,
)


SAMPLE_TEXT = """
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
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def pages(text=SAMPLE_TEXT):
    return [{"page_number": 1, "text": text, "mean_confidence": 0.94}]


def brief(text=SAMPLE_TEXT):
    return create_contract_brief(
        pages(text),
        filename="renewal-contract.txt",
        question="What is my IRD penalty?",
    )


def test_basic_interest_helpers_are_deterministic():
    assert float(annual_interest_amount(480000, 4.39)) == 21072.0
    assert float(three_month_interest_amount(480000, 4.39)) == 5268.0
    assert float(posted_discount_comparison_rate(5.69, 1.30)) == 4.39
    assert float(simple_ird_amount(480000, 4.39, 3.89, 12)) == 2400.0


def test_month_helpers_use_calendar_dates_without_external_dependencies():
    assert months_between(date(2022, 3, 1), date(2027, 3, 1)) == 60
    assert months_between(date(2022, 3, 15), date(2022, 4, 14)) == 0
    assert months_between(date(2022, 3, 15), date(2022, 4, 15)) == 1
    assert months_between(date(2027, 3, 1), date(2022, 3, 1)) == 0


def test_term_and_remaining_months_are_read_from_contract_dates():
    contract = brief()
    assert term_months_from_dates(contract) == 60
    assert remaining_months_until_maturity(contract, as_of=date(2026, 10, 13)) == 4


def test_field_dependency_map_explains_ready_and_missing_formula_inputs():
    dependencies = field_dependency_map(brief())
    assert dependencies["contract_discount"]["ready"] is True
    assert dependencies["payment_estimate"]["ready"] is True
    assert dependencies["interest_rate_differential"]["ready"] is True
    assert "posted_rate" in dependencies["contract_discount"]["requires"]
    assert "field:posted_rate" in dependencies["contract_discount"]["evidence"]

    thin = brief("Contract rate: 4.39%\nPosted rate: 5.69%")
    thin_dependencies = field_dependency_map(thin)
    assert thin_dependencies["payment_estimate"]["ready"] is False
    assert "balance" in thin_dependencies["payment_estimate"]["missing_required"]


def test_formula_walkthroughs_include_discount_penalty_and_timeline_steps():
    walk = formula_walkthroughs(brief(), as_of=date(2026, 10, 13))
    by_id = {step["id"]: step for step in walk}

    assert by_id["formula-contract-discount"]["output"] == 1.3
    assert by_id["formula-three-month-interest"]["output"] == 5268.0
    assert by_id["formula-term-timeline"]["output"]["months_between"] == 60
    assert by_id["formula-remaining-term"]["output"]["remaining_months"] == 4
    assert all(step["evidence"] for step in walk)
    assert "ABCD-1234-5678" not in str(walk)


def test_penalty_scenarios_compare_three_month_interest_and_ird():
    scenarios = penalty_scenarios(brief(), as_of=date(2026, 10, 13))
    by_id = {scenario["id"]: scenario for scenario in scenarios}

    assert by_id["three-month-interest"]["amount"] == 5268.0
    assert by_id["posted-discount-ird"]["amount"] == 0.0
    assert by_id["posted-discount-ird"]["status"] == "estimated"
    assert by_id["greater-of-visible-scenarios"]["amount"] == 5268.0
    assert "written payout statement" in by_id["greater-of-visible-scenarios"]["explanation"]


def test_penalty_scenarios_explain_missing_inputs_for_thin_documents():
    thin = brief("Contract rate: 4.39%\nPosted rate: 5.69%")
    scenarios = penalty_scenarios(thin, as_of=date(2026, 10, 13))
    by_id = {scenario["id"]: scenario for scenario in scenarios}

    assert by_id["three-month-interest"]["status"] == "missing_inputs"
    assert by_id["posted-discount-ird"]["status"] == "missing_inputs"
    assert "balance" in by_id["posted-discount-ird"]["inputs"]["missing"]


def test_renewal_disclosure_timeline_marks_21_day_window():
    contract = brief()
    early = renewal_disclosure_timeline(contract, as_of=date(2026, 10, 13))
    window = renewal_disclosure_timeline(contract, as_of=date(2027, 1, 15))
    inside = renewal_disclosure_timeline(contract, as_of=date(2027, 2, 15))
    past = renewal_disclosure_timeline(contract, as_of=date(2027, 3, 2))

    assert early["status"] == "early_review"
    assert window["status"] == "renewal_window_open"
    assert inside["status"] == "inside_21_day_window"
    assert past["status"] == "past_maturity"
    assert "21 days" in inside["fcac_renewal_notice_window"]


def test_build_contract_math_audit_returns_disclosure_prompts_and_confidence():
    audit = build_contract_math_audit_from_brief(brief(), as_of=date(2026, 10, 13))
    prompt_ids = {prompt["id"] for prompt in audit["disclosure_prompts"]}

    assert audit["provider"] == "canadian-contract-math-audit-v13"
    assert audit["confidence"]["level"] == "reviewable"
    assert audit["renewal_timeline"]["days_to_maturity"] == 139
    assert "ask-ird-method" in prompt_ids
    assert "ask-payout-statement" in prompt_ids
    assert audit["notice"].startswith("All amounts are local")


def test_math_audit_blocks_low_confidence_when_required_fields_are_missing():
    audit = build_contract_math_audit_from_brief(
        brief("Contract rate: 4.39%\nPosted rate: 5.69%"),
        as_of=date(2026, 10, 13),
    )
    prompt_ids = {prompt["id"] for prompt in audit["disclosure_prompts"]}

    assert audit["confidence"]["level"] == "low"
    assert "balance" in audit["confidence"]["missing_required"]
    assert "collect-required-fields" in prompt_ids
    assert audit["renewal_timeline"]["status"] == "missing_maturity_date"


def test_math_audit_rejects_non_v12_briefs():
    with pytest.raises(ContractMathAuditError):
        build_contract_math_audit_from_brief({"provider": "old"}, as_of=date(2026, 10, 13))
