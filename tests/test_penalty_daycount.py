from datetime import date
from decimal import Decimal as D

import pytest

from renewal.penalty.daycount import (MonthRounding, add_months, elapsed_months,
                                      prorated_clawback, remaining_term,
                                      three_month_interest_days)


@pytest.mark.parametrize('start,months,expected', [
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2028, 1, 31), 1, date(2028, 2, 29)),
    (date(2026, 11, 15), 3, date(2027, 2, 15)),
    (date(2026, 3, 31), -1, date(2026, 2, 28)),
])
def test_add_months_clamps(start, months, expected):
    assert add_months(start, months) == expected


def test_remaining_term_whole_months():
    r = remaining_term(date(2026, 10, 1), date(2028, 3, 1))
    assert (r.whole_months, r.extra_days, r.months) == (17, 0, 17)


@pytest.mark.parametrize('rounding,expected', [
    (MonthRounding.UP, 17), (MonthRounding.DOWN, 16), (MonthRounding.NEAREST, 17)])
def test_remaining_term_rounding(rounding, expected):
    r = remaining_term(date(2026, 10, 15), date(2028, 3, 1), rounding)
    assert r.whole_months == 16 and r.extra_days == 15
    assert r.months == expected


def test_nearest_rounds_short_stub_down():
    assert remaining_term(date(2026, 10, 25), date(2027, 1, 1), MonthRounding.NEAREST).months == 2


def test_remaining_term_rejects_past_maturity():
    with pytest.raises(ValueError):
        remaining_term(date(2027, 1, 2), date(2027, 1, 1))


def test_three_month_interest_uses_actual_days():
    interest, days = three_month_interest_days(D('400000'), D('5'), date(2026, 11, 1))
    assert days == 92  # Nov 1 to Feb 1: 30 + 31 + 31
    assert interest == D('400000') * D('5') / D(100) * D(92) / D(365)


def test_three_month_interest_validation():
    with pytest.raises(ValueError):
        three_month_interest_days(D('-1'), D('5'), date(2026, 1, 1))
    with pytest.raises(ValueError):
        three_month_interest_days(D('1'), D('5'), date(2026, 1, 1), day_basis=364)


def test_elapsed_and_clawback():
    assert elapsed_months(date(2023, 3, 1), date(2026, 10, 15)) == 43
    assert prorated_clawback(D('6000'), 60, 43) == D('1700')
    assert prorated_clawback(D('6000'), 60, 75) == 0
    with pytest.raises(ValueError):
        prorated_clawback(D('1'), 0, 0)
