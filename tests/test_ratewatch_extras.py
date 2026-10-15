"""Tests for the decision helpers and their API routes (offline)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import extras as x
from renewal.ratewatch.ird import Mortgage, POLICIES, penalty

client = TestClient(app)
TD = POLICIES["TD"]
TABLE = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}
DAY = date(2026, 10, 14)
BODY = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
        "maturity": "2028-10-15", "discount": 2.0, "payout": "2026-10-14",
        "current_posted": {str(k): v for k, v in TABLE.items()}}


def mortgage():
    return Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.0, maturity=date(2028, 10, 15))


def test_break_even_uses_penalty_plus_fees():
    r = x.break_even(mortgage(), TD, TABLE, DAY, 3.99, fees=1200)
    assert r["penalty_plus_fees"] == 14032.0 and r["first_month_interest_saving"] > 0
    # 24 months of interest savings do not recover $14,032, so there is no break-even inside the term
    assert r["break_even_months"] is None and r["worth_it_within_remaining_term"] is False


def test_cheapest_day_is_not_maturity_and_not_more_than_today():
    r = x.cheapest_day(mortgage(), TD, TABLE, DAY)
    assert r["penalty"] <= r["today"] and r["date"] < "2028-10-15"


def test_blend_is_weighted_average():
    r = x.blend_and_extend(mortgage(), DAY, 4.0, 60, TD, TABLE)
    expected = (4.89 * r["remaining_months"] + 4.0 * (60 - r["remaining_months"])) / 60
    assert r["blended_rate"] == pytest.approx(expected, abs=0.001)


def test_lump_sum_reduces_penalty():
    r = x.lump_sum_first(mortgage(), TD, TABLE, DAY, 15)
    assert r["saved"] > 0 and r["penalty_after_lump_sum"] < r["penalty_without"]


def test_sensitivity_lower_posted_means_higher_penalty():
    rows = x.sensitivity(mortgage(), TD, TABLE, DAY)
    pens = [r["penalty"] for r in rows]
    assert pens == sorted(pens, reverse=True)


def test_port_vs_break():
    assert x.port_vs_break(mortgage(), TD, TABLE, DAY, port_fee=500)["cheaper"] == "port"


def test_renewal_countdown_window():
    r = x.renewal_countdown(mortgage(), date(2028, 7, 1))
    assert r["early_renewal_window_opens"] == "2028-06-17" and r["in_window"]


def test_stress_test_floor_and_plus_two():
    assert x.stress_test(400_000, 2.5)["qualifying_rate"] == 5.25
    assert x.stress_test(400_000, 4.89)["qualifying_rate"] == 6.89


def test_net_switch_benefit_subtracts_penalty_and_fees():
    r = x.net_switch_benefit(mortgage(), TD, TABLE, DAY, 3.99, 1200)
    assert r["net_benefit"] == pytest.approx(r["interest_saved"] - r["penalty"] - 1200, abs=0.01)


def test_reverse_rate_reports_ranges_not_a_false_unique_answer():
    exact = x.reverse_rate(mortgage(), TD, DAY, 12832.0)
    (lo, hi), = exact["compatible_posted_rate_ranges"]
    assert lo <= 5.29 <= hi and hi - lo < 0.001 and exact["unique"]
    floor = x.reverse_rate(mortgage(), TD, DAY, 4890.0)             # quote equals three months' interest
    lo, hi = floor["compatible_posted_rate_ranges"][0]
    assert not floor["unique"] and hi - lo > 5                      # many posted rates fit


def test_heatmap_is_labelled_hypothetical_and_shows_waiting_cost():
    h = x.heatmap(mortgage(), TD, TABLE, DAY, months_ahead=3)
    assert h["label"].startswith("HYPOTHETICAL")
    assert h["rows"][0]["interest_paid_while_waiting"] == 0 and h["rows"][3]["interest_paid_while_waiting"] > 0


def test_csv_and_summary_text():
    r = penalty(mortgage(), TD, TABLE, DAY)
    csv_text = x.to_csv(r, [])
    assert "penalty,12832.0" in csv_text
    assert "$12,832.00" in x.summary_text("TD", r) and "12 832,00 $" in x.summary_text("TD", r, language="fr")


@pytest.mark.parametrize("tool", ["break-even", "cheapest-day", "blend", "lump-sum", "sensitivity", "port-vs-break",
                                  "countdown", "stress-test", "net-switch", "reverse-rate", "heatmap", "summary", "csv"])
def test_every_extras_route_responds(tool):
    r = client.post(f"/api/ratewatch/extras/{tool}", json={**BODY, "new_rate": 3.99, "quoted_penalty": 12832.0})
    assert r.status_code == 200, r.text


def test_extras_route_requires_new_rate():
    assert client.post("/api/ratewatch/extras/break-even", json=BODY).status_code == 422


def test_french_letter_route():
    import pymupdf
    r = client.post("/api/ratewatch/letter", json={**BODY, "client_name": "Alex Sample", "language": "fr"})
    text = pymupdf.open(stream=r.content, filetype="pdf")[0].get_text()
    assert r.status_code == 200 and "Pénalité estimée" in text
