"""Date arithmetic for prepayment charges.

Contracts describe time left on a term in months, while a payout happens on a
specific day. These helpers convert dates into the month counts the IRD needs
and give day-exact three-month interest for contracts that charge by days.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

D = Decimal


class MonthRounding(str, Enum):
    UP = 'up'          # any part month counts as a month (borrower pays more)
    DOWN = 'down'      # only whole months count
    NEAREST = 'nearest'


def add_months(day: date, months: int) -> date:
    """Calendar month shift that clamps to month end (Jan 31 + 1 month = Feb 28/29)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class RemainingTerm:
    whole_months: int
    extra_days: int
    months: int
    rounding: MonthRounding

    def as_dict(self) -> dict:
        return {'whole_months': self.whole_months, 'extra_days': self.extra_days,
                'months': self.months, 'rounding': self.rounding.value}


def remaining_term(payout: date, maturity: date,
                   rounding: MonthRounding = MonthRounding.UP) -> RemainingTerm:
    """Months from payout to maturity, with the contract's rounding of part months."""
    if maturity < payout:
        raise ValueError('maturity date is before the payout date')
    whole = (maturity.year - payout.year) * 12 + (maturity.month - payout.month)
    if add_months(payout, whole) > maturity:
        whole -= 1
    extra = (maturity - add_months(payout, whole)).days
    if extra == 0 or rounding is MonthRounding.DOWN:
        months = whole
    elif rounding is MonthRounding.UP:
        months = whole + 1
    else:
        span = (add_months(payout, whole + 1) - add_months(payout, whole)).days
        months = whole + (1 if extra * 2 >= span else 0)
    return RemainingTerm(whole, extra, months, rounding)


def three_month_interest_days(principal: D, annual_rate_pct: D, payout: date,
                              *, day_basis: int = 365) -> tuple[D, int]:
    """Interest on ``principal`` for the actual days in the next three calendar months.

    Returns ``(interest, days)``. Rates are percentage points (5.25 = 5.25%).
    """
    if principal < 0:
        raise ValueError('principal cannot be negative')
    if day_basis not in (360, 365):
        raise ValueError('day_basis must be 360 or 365')
    days = (add_months(payout, 3) - payout).days
    return principal * annual_rate_pct / D(100) * D(days) / D(day_basis), days


def elapsed_months(start: date, payout: date) -> int:
    """Whole months elapsed since the term started (used for cashback clawbacks)."""
    if payout < start:
        raise ValueError('payout date is before the term start')
    return remaining_term(start, payout, MonthRounding.DOWN).months


def prorated_clawback(cashback: D, term_months: int, months_elapsed: int) -> D:
    """Straight-line share of a cash-back incentive still owed on early payout."""
    if term_months <= 0:
        raise ValueError('term_months must be positive')
    if cashback < 0:
        raise ValueError('cashback cannot be negative')
    left = max(0, term_months - max(0, months_elapsed))
    return cashback * D(left) / D(term_months)
