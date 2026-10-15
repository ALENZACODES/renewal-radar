"""Hand-computed penalty cases. Run: python -m pytest tests -q   (or python tests/test_ird.py)"""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from renewal.ratewatch.ird import BIG6, Mortgage, Policy, POLICIES, calibrate, forecast, penalty, pick_term, td_months_remaining

GENERIC = Policy("Generic big bank", **BIG6)   # calendar months, nearest term

TODAY_POSTED = {12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09}


def big6_case():
    # $400k at 4.89%, 5yr from 2023-10-15, posted then 6.89 -> discount 2.00
    return Mortgage(400_000, 4.89, 60, date(2023, 10, 15), {60: 6.89})


def test_posted_discount_ird():
    r = penalty(big6_case(), GENERIC, TODAY_POSTED, date(2026, 10, 15))
    # 24 months left -> 2yr posted 5.29 - 2.00 = 3.29; diff 1.60; 400000*0.016*2 = 12,800
    assert r["compare_term"] == 24 and r["compare_rate"] == 3.29
    assert r["ird"] == 12_800.00 and r["three_month"] == 4_890.00 and r["penalty"] == 12_800.00


def test_welcome_package_discount_overrides_inferred():
    m = big6_case()
    m.discount = 1.75
    r = penalty(m, GENERIC, TODAY_POSTED, date(2026, 10, 15))
    assert r["compare_rate"] == 3.54 and r["ird"] == round(400_000 * 0.0135 * 2, 2)


def test_tie_breaks_down_and_transition():
    p = Policy("x")
    assert pick_term(30, p, TODAY_POSTED)[0] == 24
    assert pick_term(30.01, p, TODAY_POSTED)[0] == 36
    assert pick_term(30, Policy("x", tie_break="up"), TODAY_POSTED)[0] == 36


def test_first_months_are_three_month_interest():
    # 4.6 years left -> nearest is 5yr; posted unchanged at 6.89 -> compare = contract -> IRD 0
    r = penalty(big6_case(), POLICIES["TD"], {**TODAY_POSTED, 60: 6.89}, date(2024, 3, 1))
    assert r["method"] == "3-month" and r["ird"] == 0


def test_cibc_three_month_on_posted():
    r = penalty(big6_case(), POLICIES["CIBC"], {**TODAY_POSTED, 60: 6.89}, date(2024, 3, 1))
    assert r["three_month"] == round(400_000 * 0.0689 / 4, 2)


def test_offered_rate_method():
    m = Mortgage(300_000, 5.24, 60, date(2024, 4, 1), discount=0)
    r = penalty(m, POLICIES["First National"], {}, date(2026, 10, 1), current_offered={12: 4.9, 24: 4.4, 36: 4.2})
    # 30 months left, tie -> 24m offered 4.40; diff 0.84; 300000*0.0084*2.5 = 6,300
    assert r["compare_term"] == 24 and r["ird"] == 6_300.00


def test_interest_act_cap_after_year_five():
    m = Mortgage(500_000, 6.0, 120, date(2018, 1, 1), {120: 7.0})
    r = penalty(m, POLICIES["RBC"], {12: 3.0, 24: 3.0, 36: 3.0, 48: 3.0, 60: 3.0}, date(2024, 2, 1))
    assert r["penalty"] == 7_500.00 and any("Interest Act" in n for n in r["notes"])


def test_no_negative_ird():
    r = penalty(big6_case(), POLICIES["TD"], {k: 9.0 for k in TODAY_POSTED}, date(2026, 10, 15))
    assert r["ird"] == 0 and r["penalty"] == r["three_month"]


def test_calibrate_recovers_policy():
    m, payout = big6_case(), date(2026, 10, 15)
    truth = Policy("Mystery", term_match="round_up", time_basis="days")
    actual = penalty(m, truth, TODAY_POSTED, payout)["penalty"]
    hits = calibrate(m, TODAY_POSTED, payout, actual, tol=0.5, lender="Mystery")
    assert any(h[1].term_match == "round_up" and h[1].time_basis == "days" for h in hits)


def test_forecast_flags_transitions():
    full = {6: 5.54, **TODAY_POSTED, 72: 6.29, 84: 6.4, 120: 6.8}       # TD needs every band, incl. 6-month
    rows = forecast(big6_case(), POLICIES["TD"], full, date(2026, 10, 15))
    assert any(r["transition"] for r in rows)


def test_td_bands_from_tds_own_code():
    td = POLICIES["TD"]
    t6 = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}
    assert pick_term(30, td, t6)[0] == 36          # TD: 30-41.999 months -> 3-year (not the 2-year)
    assert pick_term(29.99, td, t6)[0] == 24
    assert pick_term(8.9, td, t6)[0] == 6           # under 9 months -> 6-month rate
    assert pick_term(80, td, t6)[0] == 84           # 78-101.999 -> 7-year


def test_td_months_remaining_matches_tds_javascript():
    assert td_months_remaining(date(2026, 10, 14), date(2028, 10, 15)) == 24.06
    assert td_months_remaining(date(2026, 10, 14), date(2028, 10, 14)) == 24.03   # JS day-0 roll-back


def test_td_sample_equals_td_calculator():
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.0, maturity=date(2028, 10, 15))
    r = penalty(m, POLICIES["TD"], {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8},
                date(2026, 10, 14))
    assert r["ird"] == 12_832.00 and r["three_month"] == 4_890.00      # TD's own code returns the same


def test_half_up_rounding_like_td():
    m = Mortgage(954_634.75, 8.0, 12, date(2026, 7, 11), discount=2.04, maturity=date(2027, 7, 11))
    r = penalty(m, POLICIES["TD"], {6: 7.92, 12: 7.0}, date(2026, 10, 14))
    assert r["three_month"] == 19_092.70


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
