import math
from datetime import date

import pytest

from renewal.broker.book_ingest import Deal
from renewal.broker import book_economics as economics
from renewal.ratewatch.extras import _interest_path, monthly_payment
from renewal.ratewatch.ird import Mortgage, balance_after


@pytest.mark.parametrize("rate", [0, 1.25, 4.89, 6.5, 15])
@pytest.mark.parametrize("periods", [12, 24, 26, 52])
def test_periodic_rates_reproduce_semiannual_compounding(rate, periods):
    periodic = economics.periodic_interest(rate, periods)
    annual = (1 + periodic) ** periods
    assert annual == pytest.approx((1 + rate / 200) ** 2, rel=1e-12)


def test_monthly_payment_matches_existing_engine():
    for amount, rate, amort in [(100000, 4.5, 120), (400000, 6.5, 300), (750000, 2.1, 360)]:
        assert economics.scheduled_payment(amount, rate, amort) == pytest.approx(
            monthly_payment(amount, rate, amort), abs=1e-7
        )


@pytest.mark.parametrize("frequency", list(economics.PER_YEAR))
def test_payment_schedule_never_invents_negative_interest(frequency):
    schedule = economics.payment_schedule(12000, 5.25, 12, date(2024, 1, 1), frequency)
    assert schedule
    assert all(row.interest >= 0 for row in schedule)
    assert all(row.principal > 0 for row in schedule)
    assert schedule[-1].closing_balance == pytest.approx(0, abs=1e-7)
    assert sum(row.principal for row in schedule) == pytest.approx(12000, abs=1e-7)
    assert sum(row.payment for row in schedule) == pytest.approx(
        12000 + sum(row.interest for row in schedule), abs=1e-7
    )
    assert all(a.due < b.due for a, b in zip(schedule, schedule[1:]))


def test_month_end_schedule_does_not_drift():
    schedule = economics.payment_schedule(100000, 5, 120, date(2024, 1, 31), through=date(2024, 4, 30))
    assert [row.due for row in schedule] == [
        date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30),
    ]
    assert [row.number for row in schedule] == [1, 2, 3]


def test_projection_stops_at_review_date():
    schedule = economics.payment_schedule(
        100000, 5, 120, date(2024, 1, 1), through=date(2024, 3, 15)
    )
    assert len(schedule) == 2
    assert schedule[-1].due == date(2024, 3, 1)


def test_balance_before_first_payment_is_the_advance():
    deal = Deal("X", balance=100000, contract_rate=5, term_months=60,
                closing_date=date(2024, 1, 1), amort_months=300,
                balance_basis="original", amort_basis="original", rate_type="fixed")
    projected = economics.project_balance(deal, date(2024, 1, 20))
    assert projected["balance"] == 100000
    assert projected["payments_modelled"] == 0
    assert projected["estimated"]


def test_monthly_projection_agrees_with_legacy_balance_formula():
    deal = Deal("X", balance=400000, contract_rate=4.89, term_months=60,
                closing_date=date(2023, 1, 1), amort_months=300,
                balance_basis="original", amort_basis="original", rate_type="fixed", frequency="monthly")
    projected = economics.project_balance(deal, date(2024, 1, 1))
    mortgage = Mortgage(400000, 4.89, 60, date(2023, 1, 1), amort_months=300)
    assert projected["balance"] == pytest.approx(balance_after(mortgage, 12), abs=0.01)
    assert projected["remaining_amort_months"] == 288


def test_accelerated_payments_reduce_the_balance_faster():
    regular = economics.payment_schedule(400000, 5, 300, date(2023, 1, 1),
                                         "biweekly", through=date(2024, 1, 1))
    accelerated = economics.payment_schedule(400000, 5, 300, date(2023, 1, 1),
                                             "accelerated_biweekly", through=date(2024, 1, 1))
    assert len(regular) == len(accelerated) == 26
    assert accelerated[-1].closing_balance < regular[-1].closing_balance


def test_stated_regular_payment_changes_original_balance_projection():
    default = economics.payment_schedule(100000, 5, 300, date(2023, 1, 1), through=date(2024, 1, 1))
    larger = economics.payment_schedule(100000, 5, 300, date(2023, 1, 1),
                                        payment=1000, through=date(2024, 1, 1))
    assert larger[-1].closing_balance < default[-1].closing_balance
    assert all(row.payment == 1000 for row in larger)


def test_last_payment_is_capped_at_what_is_owed():
    rows = economics.payment_schedule(1000, 5, 120, date(2024, 1, 1), payment=900)
    assert len(rows) == 2
    assert rows[-1].payment < 900
    assert rows[-1].closing_balance == 0
    assert rows[-1].principal == pytest.approx(rows[-1].opening_balance)


def test_zero_interest_schedule_and_repayment():
    rows = economics.payment_schedule(1200, 0, 12, date(2024, 1, 1))
    assert len(rows) == 12
    assert sum(row.interest for row in rows) == 0
    assert sum(row.payment for row in rows) == 1200
    assert economics.repayment_periods(1200, 0, 100) == 12


@pytest.mark.parametrize("change", [
    {"balance": -1},
    {"balance": float("inf")},
    {"annual_rate": 99},
    {"amort_months": 0},
    {"amort_months": 481},
    {"frequency": "daily"},
    {"payment": 1},
    {"max_periods": 100000},
])
def test_invalid_schedules_fail_with_domain_errors(change):
    request = dict(balance=100000, annual_rate=5, amort_months=300, start=date(2024, 1, 1))
    with pytest.raises(ValueError):
        economics.payment_schedule(**{**request, **change})


def test_original_variable_advance_is_not_projected_with_one_rate():
    deal = Deal("V", balance=400000, contract_rate=5, amort_months=300,
                closing_date=date(2023, 1, 1), rate_type="variable",
                balance_basis="original", amort_basis="original")
    with pytest.raises(ValueError, match="variable"):
        economics.project_balance(deal, date(2024, 1, 1))


def test_old_statement_balance_cannot_be_treated_as_current():
    deal = Deal("D", balance=400000, balance_date=date(2024, 1, 1))
    with pytest.raises(ValueError, match="differs"):
        economics.project_balance(deal, date(2024, 2, 1))


def test_same_payment_uses_the_actual_frequency():
    monthly = economics.same_payment_projection(200000, 6.5, 4.5, 300, 5000, 1000, 1500, "monthly")
    biweekly = economics.same_payment_projection(200000, 6.5, 4.5, 300, 5000, 1000, 1500, "biweekly")
    assert monthly["periods_per_year"] == 12
    assert biweekly["periods_per_year"] == 26
    assert monthly["years_saved"] != biweekly["years_saved"]
    assert biweekly["costs_financed"] == 6000
    assert "Hypothetical" in monthly["label"]


def test_same_payment_formula_matches_independent_annuity_solution():
    result = economics.same_payment_projection(200000, 6.5, 4.5, 300, 5000, 0, 1500, "biweekly")
    old_j = (1 + 6.5 / 200) ** (2 / 26) - 1
    new_j = (1 + 4.5 / 200) ** (2 / 26) - 1
    old_periods = -math.log(1 - 200000 * old_j / 1500) / math.log(1 + old_j)
    new_periods = -math.log(1 - 205000 * new_j / 1500) / math.log(1 + new_j)
    assert result["years_saved"] == round((old_periods - new_periods) / 26, 2)


def test_payment_below_interest_has_no_payoff_projection():
    result = economics.same_payment_projection(500000, 6.5, 4.5, 300, 5000, 0, 500, "monthly")
    assert result["old_periods"] is None
    assert result["years_saved"] is None


def test_cash_costs_are_subtracted_once():
    result = economics.interest_comparison(400000, 6.5, 4.4, 300, 24, 10000, 1500)
    expected = sum(_interest_path(400000, 6.5, 300, 24)) - sum(_interest_path(400000, 4.4, 300, 24))
    assert result["interest_saved"] == round(expected, 2)
    assert result["net_benefit"] == round(expected - 11500, 2)
    assert result["monthly"][-1]["net_after_costs"] == result["net_benefit"]


def test_cash_break_even_matches_the_first_positive_month():
    result = economics.interest_comparison(400000, 6.5, 4.4, 300, 24, 5000, 500)
    positive = [r["month"] for r in result["monthly"] if r["net_after_costs"] >= 0]
    assert result["break_even_months"] == positive[0]


def test_higher_new_rate_never_manufactures_a_saving():
    result = economics.interest_comparison(400000, 4.5, 7, 6, 24, 4500)
    assert result["interest_saved"] < 0
    assert result["net_benefit"] < -4500
    assert result["break_even_months"] is None
    assert all(r["old_interest"] >= 0 and r["new_interest"] >= 0 for r in result["monthly"])


def test_waiting_uses_the_same_end_date_without_double_counting():
    result = economics.wait_economics(400000, 6.5, 4.4, 300, 24, 3, 8000, 500)
    mortgage = Mortgage(400000, 6.5, 60, date(2024, 1, 1), amort_months=300)
    later_balance = balance_after(mortgage, 3)
    expected = economics.interest_comparison(later_balance, 6.5, 4.4, 297, 21, 8000, 500)
    assert result["net_benefit"] == expected["net_benefit"]
    assert result["horizon_months"] == 21
    assert result["common_horizon_months"] == 24
    assert result["early_interest_saving_forgone"] > 0
    assert "cancels" in result["basis"]


@pytest.mark.parametrize("months", [0, 24, 25, -1])
def test_waiting_must_leave_a_comparable_horizon(months):
    with pytest.raises(ValueError):
        economics.wait_economics(400000, 6.5, 4.4, 300, 24, months, 8000)


def test_waiting_after_full_repayment_has_no_switch():
    assert economics.wait_economics(1000, 5, 4, 1, 12, 3, 100) is None


def test_row_serialization_contains_only_rounded_money_and_iso_dates():
    row = economics.payment_schedule(10000, 5, 120, date(2024, 1, 1))[0]
    serialized = row.as_dict()
    assert serialized["due"] == "2024-02-01"
    assert serialized["number"] == 1
    assert serialized["opening_balance"] == 10000
    assert serialized["interest"] == round(row.interest, 2)
