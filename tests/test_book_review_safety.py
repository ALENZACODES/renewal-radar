import csv
import io
from datetime import date

import pytest

from renewal.broker import book_review as review
from renewal.broker.book_ingest import Deal, deal_from_dict
from renewal.broker.book_validation import (
    lender_alias_matches, offer_issues, source_date, validate_deal, validate_rate_table,
)
from renewal.ratewatch import history
from renewal.ratewatch.ird import Mortgage, POLICIES, penalty

DAY = date(2026, 10, 15)
TABLE = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}


def deal(**changes):
    data = {
        "deal_id": "D1", "borrower": "Fictional Client", "lender": "TD Canada Trust",
        "rate_type": "fixed", "balance": 500000, "contract_rate": 6.5,
        "posted_rate": 8.0, "term_months": 60, "closing_date": "2023-10-16",
        "maturity_date": "2028-10-16", "amort_months": 300,
    }
    return {**data, **changes}


def board(captured="2026-10-15", posted=6.19, special=4.4):
    return {
        "banks": [{
            "name": "RBC", "lender_specific": True, "as_of": captured, "tier_label": "Live",
            "rates": {"60": {"posted": posted, "special": special}},
        }],
        "credit_unions": [],
    }


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(review, "_board", board)
    history.save("P023", "2026-10-14", [(t, "fixed_closed", "posted", r) for t, r in TABLE.items()], "api")


def result(**changes):
    return review.review_book([deal(**changes)], as_of=DAY)["results"][0]


@pytest.mark.parametrize("name,expected", [
    ("TD Canada Trust", "TD"),
    ("Toronto-Dominion", "TD"),
    ("RBC Royal Bank", "RBC"),
    ("MCAP Financial Ltd.", "MCAP"),
    ("Home Trust Ltd", "Home Trust"),
    ("First National Financial LP", "First National"),
    ("Example Mortgage Ltd.", "Example Mortgage Ltd."),
])
def test_lender_resolution_never_matches_td_inside_ltd(name, expected):
    policy, source, canonical = review.resolve_lender(name)
    assert canonical == expected
    if expected != "TD":
        assert source != "P023"
        assert policy.lender != "TD"


def test_aliases_match_complete_words():
    assert lender_alias_matches("TD Canada Trust", "td")
    assert not lender_alias_matches("Mortgage Ltd.", "td")
    assert not lender_alias_matches("RBCish Funding", "rbc")
    assert lender_alias_matches("Bank of Nova Scotia", "bank of nova scotia")


@pytest.mark.parametrize("captured", ["2020-01-01", "2026-10-16", None, "not a date"])
def test_stale_future_or_undated_offers_cannot_recommend_a_break(captured, monkeypatch):
    monkeypatch.setattr(review, "_board", lambda: board(captured))
    response = result()
    assert response["status"] == "needs_data"
    assert response["net_benefit"] is None
    assert "best_offer" not in response


def test_cached_offer_is_not_a_strong_recommendation(monkeypatch):
    monkeypatch.setattr(review, "_board", lambda: board("2026-10-12"))
    response = result(contract_rate=8, posted_rate=9)
    assert response["status"] != "strong"
    assert any("3 days old" in issue for issue in response["issues"])


@pytest.mark.parametrize("posted,special", [(3, 4), (6, -1), (6, float("inf")), (6, 31)])
def test_bad_offer_rates_are_excluded(posted, special):
    assert review.best_offers(board=board(posted=posted, special=special), as_of=DAY) == []


def test_broker_target_does_not_need_or_use_a_live_offer():
    response = review.review_book([deal()], as_of=DAY, target_rate=4.1)
    assert response["best_offer"]["lender"] == "broker target"
    assert response["top_offers"] == []
    assert response["results"][0]["best_offer"]["rate"] == 4.1


def test_future_market_data_is_not_used_in_a_historical_review():
    response = review.review_book([deal()], as_of=date(2026, 10, 1))
    assert response["best_offer"] is None
    assert response["results"][0]["status"] == "needs_data"


def test_cibc_three_month_basis_keeps_original_posted_rate():
    history.save("P029", "2026-10-14", [(t, "fixed_closed", "posted", 9) for t in TABLE], "api")
    response = result(lender="CIBC")
    assert response["penalty"]["three_month"] == 10000
    mortgage = Mortgage(500000, 6.5, 60, date(2023, 10, 16), {60: 8}, 1.5,
                        amort_months=300, maturity=date(2028, 10, 16))
    expected = penalty(mortgage, POLICIES["CIBC"], {t: 9 for t in TABLE}, DAY)
    assert response["penalty"]["penalty"] == expected["penalty"]


def test_cibc_missing_original_posted_cannot_use_contract_rate_floor():
    history.save("P029", "2026-10-14", [(t, "fixed_closed", "posted", 9) for t in TABLE], "api")
    response = result(lender="CIBC", posted_rate=None, discount=1.5)
    assert response["status"] == "needs_data"
    assert "original posted rate" in response["recommendation"]


def test_unknown_rate_type_blocks_instead_of_assuming_fixed():
    response = result(rate_type="unconfirmed")
    assert response["status"] == "needs_data"
    assert "penalty" not in response
    assert any(i["code"] == "unknown_rate_type" for i in response["validation"])


def test_open_fixed_contract_does_not_use_closed_mortgage_charge():
    response = result(product="Fixed Open Mortgage")
    assert response["status"] == "needs_data"
    assert "penalty" not in response
    assert any(i["code"] == "open_contract" for i in response["validation"])


def test_ocr_warning_survives_review_and_blocks_unconfirmed_records():
    response = result(source="ocr", issues=["read by OCR: verify every value"])
    assert response["status"] == "needs_data"
    assert "read by OCR: verify every value" in response["issues"]
    assert any(i["code"] == "ocr_unverified" for i in response["validation"])
    confirmed = result(source="ocr", review_confirmed=True)
    assert "penalty" in confirmed


@pytest.mark.parametrize("field,value", [
    ("balance", None), ("amort_months", 0), ("term_months", 0),
    ("contract_rate", float("nan")), ("frequency", "daily"),
    ("posted_rate", 1), ("balance_basis", "unknown"), ("amort_basis", "unknown"),
])
def test_unsafe_deal_values_do_not_receive_recommendations(field, value):
    response = result(**{field: value})
    assert response["status"] == "needs_data"
    assert response["net_benefit"] is None
    assert "penalty" not in response


@pytest.mark.parametrize("status", ["Cancelled", "Declined", "Withdrawn", "Approved", "Draft", "Not funded"])
def test_nonfunded_pipeline_records_are_not_break_opportunities(status):
    response = result(status=status)
    assert response["status"] == "needs_data"
    assert any(i["code"] == "not_funded_status" for i in response["validation"])


def test_term_and_maturity_conflict_blocks_even_if_maturity_has_passed():
    response = result(maturity_date="2026-09-01")
    assert response["status"] == "needs_data"
    assert any(i["code"] == "term_date_conflict" for i in response["validation"])


def test_stale_statement_balance_requires_an_updated_statement():
    response = result(balance_date="2026-09-01")
    assert response["status"] == "needs_data"
    assert any(i["code"] == "stale_balance" for i in response["validation"])


def test_original_amount_with_remaining_amortization_is_not_reprojected():
    response = result(balance_basis="original", amort_basis="remaining")
    assert response["status"] == "needs_data"
    assert any(i["code"] == "original_amort_required" for i in response["validation"])


def test_original_variable_amount_requires_current_balance():
    response = result(balance_basis="original", amort_basis="original", rate_type="variable")
    assert response["status"] == "needs_data"
    assert "penalty" not in response


def test_duplicate_deals_do_not_double_the_opportunity_total():
    one = review.review_book([deal()], as_of=DAY)
    duplicate = review.review_book([deal(), deal(deal_id="d1")], as_of=DAY)
    assert duplicate["deals_reviewed"] == 1
    assert duplicate["total_net_benefit"] == one["total_net_benefit"]
    assert len(duplicate["duplicates"]) == 1
    assert duplicate["deals_input"] == 2


def test_missing_identifiers_get_distinct_row_ids():
    first = deal()
    first.pop("deal_id")
    second = {**first, "balance": 300000}
    response = review.review_book([first, second], as_of=DAY)
    assert response["deals_reviewed"] == 2
    assert {r["deal_id"] for r in response["results"]} == {"row-1", "row-2"}


def test_supplied_payment_frequency_reaches_years_projection():
    response = result(balance=200000, payment=1500, frequency="biweekly")
    projection = response["same_payment_projection"]
    assert projection["frequency"] == "biweekly"
    assert projection["periods_per_year"] == 26
    assert projection["payment"] == 1500
    assert "Hypothetical" in projection["label"]


def test_cash_economics_are_reconcilable_per_month():
    response = result()
    path = response["economics"]["monthly"]
    assert response["net_benefit"] == path[-1]["net_after_costs"]
    assert response["interest_saved"] == pytest.approx(
        sum(row["old_interest"] - row["new_interest"] for row in path), abs=0.1
    )


def test_waiting_comparison_reports_one_common_end_date(monkeypatch):
    real_penalty = review.penalty
    def falling_charge(mortgage, policy, rates, payout, **kwargs):
        charge = real_penalty(mortgage, policy, rates, payout, **kwargs)
        charge["penalty"] = 50000 if payout == DAY else 0
        return charge
    monkeypatch.setattr(review, "penalty", falling_charge)
    data = deal(contract_rate=8, posted_rate=9)
    response = review.review_book([data], as_of=DAY, target_rate=3.5)["results"][0]
    later = response["better_date"]["comparison"]
    assert later["common_horizon_months"] == response["horizon_months"]
    assert later["horizon_months"] + later["wait_months"] == response["horizon_months"]
    assert response["better_date"]["net_benefit"] > response["net_benefit"]
    assert "Break now" not in response["recommendation"]


def test_history_lookup_preserves_explicit_discount(monkeypatch):
    history.save("P029", "2026-10-14", [(t, "fixed_closed", "posted", 9) for t in TABLE], "api")
    history.save("P029", "2023-10-16", [(60, "fixed_closed", "posted", 8.5)], "api")
    captured = []
    real_penalty = review.penalty
    def observe(mortgage, *args, **kwargs):
        captured.append(mortgage.discount)
        return real_penalty(mortgage, *args, **kwargs)
    monkeypatch.setattr(review, "penalty", observe)
    response = result(lender="CIBC", posted_rate=None, discount=1.5)
    assert "penalty" in response
    assert captured and all(value == 1.5 for value in captured)
    assert response["penalty"]["three_month"] == 10625


def test_csv_neutralizes_formulas_without_losing_amounts():
    response = review.review_book([deal(deal_id="=1+1", borrower="@SUM(A1)")], as_of=DAY)
    exported = list(csv.DictReader(io.StringIO(review.to_csv(response))))[0]
    assert exported["deal_id"] == "'=1+1"
    assert exported["borrower"] == "'@SUM(A1)"
    assert float(exported["balance_today"]) == 500000


def test_diagnostics_count_missing_data_without_storing_records():
    response = review.review_book([deal(rate_type=None)], as_of=DAY)
    assert response["diagnostics"]["blocked_deals"] == 1
    assert response["diagnostics"]["issue_counts"]["unknown_rate_type"] == 1
    assert response["diagnostics"]["recommendations_are_quotes"] is False


def test_rate_table_validation_rejects_bad_values_and_terms():
    assert validate_rate_table({24: 5.5, 60: 6})
    assert not validate_rate_table({9999: 5.5})
    assert not validate_rate_table({24: -1})
    assert not validate_rate_table({24: float("nan")})
    assert not validate_rate_table({})
    assert not validate_rate_table({"24": 5.5})


def test_source_dates_include_iso_and_archive_provenance():
    assert source_date("2026-10-15T10:00:00Z") == DAY
    assert source_date("wayback 20261015") == DAY
    assert source_date("common crawl 20261015") == DAY
    assert source_date("wayback 20260231") is None


def test_offer_source_reports_staleness():
    offer = {"rate": 4.4, "posted": 6, "labelled": True, "as_of": "2026-10-01"}
    issues = offer_issues(offer, DAY)
    assert any(i.code == "cached_offer" and not i.blocking for i in issues)
    expired = offer_issues({**offer, "as_of": "2026-09-30"}, DAY)
    assert any(i.code == "offer_expired" and i.blocking for i in expired)
