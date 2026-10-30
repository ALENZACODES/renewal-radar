"""Auditable payment schedules and like-for-like broker-book comparisons."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from ..ratewatch.extras import _interest_path, monthly_payment
from ..ratewatch.ird import add_months, months_between
from .book_values import finite_number, payment_frequency

PER_YEAR = {
    "monthly": 12,
    "semi_monthly": 24,
    "biweekly": 26,
    "weekly": 52,
    "accelerated_biweekly": 26,
    "accelerated_weekly": 52,
}


@dataclass(frozen=True)
class PaymentRow:
    number: int
    due: date
    opening_balance: float
    interest: float
    payment: float
    principal: float
    closing_balance: float

    def as_dict(self):
        result = asdict(self)
        result["due"] = self.due.isoformat()
        for key in ("opening_balance", "interest", "payment", "principal", "closing_balance"):
            result[key] = round(result[key], 2)
        return result


def _positive(value, name, maximum=100_000_000):
    result = finite_number(value, 0.000001, maximum)
    if result is None:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def periodic_interest(annual_rate: float, periods: int) -> float:
    rate = finite_number(annual_rate, 0, 30)
    if rate is None or periods not in (12, 24, 26, 52):
        raise ValueError("unsupported rate or payment frequency")
    return (1 + rate / 200) ** (2 / periods) - 1


def scheduled_payment(balance, annual_rate, amort_months, frequency="monthly") -> float:
    balance = _positive(balance, "balance")
    amort = finite_number(amort_months, 1, 480)
    freq = payment_frequency(frequency)
    if amort is None or not float(amort).is_integer() or freq is None:
        raise ValueError("valid amortization and payment frequency required")
    if freq == "accelerated_biweekly":
        return monthly_payment(balance, annual_rate, int(amort)) / 2
    if freq == "accelerated_weekly":
        return monthly_payment(balance, annual_rate, int(amort)) / 4
    count = PER_YEAR[freq]
    interest = periodic_interest(annual_rate, count)
    periods = amort * count / 12
    if interest == 0:
        return balance / periods
    return balance * interest / (1 - (1 + interest) ** -periods)


def due_date(start: date, number: int, frequency: str) -> date:
    if number < 1:
        raise ValueError("payment numbers start at one")
    freq = payment_frequency(frequency)
    if freq == "monthly":
        return add_months(start, number)
    if freq == "semi_monthly":
        months, half = divmod(number, 2)
        anchor = add_months(start, months)
        return min(anchor + timedelta(days=15), add_months(start, months + 1)) if half else anchor
    if freq in ("biweekly", "accelerated_biweekly"):
        return start + timedelta(days=14 * number)
    if freq in ("weekly", "accelerated_weekly"):
        return start + timedelta(days=7 * number)
    raise ValueError("unsupported payment frequency")


def payment_schedule(
    balance: float,
    annual_rate: float,
    amort_months: int,
    start: date,
    frequency: str = "monthly",
    payment: float | None = None,
    through: date | None = None,
    max_periods: int = 2500,
) -> list[PaymentRow]:
    balance = _positive(balance, "balance")
    freq = payment_frequency(frequency)
    if freq is None:
        raise ValueError("payment frequency not recognized")
    periods = PER_YEAR[freq]
    rate = periodic_interest(annual_rate, periods)
    expected = scheduled_payment(balance, annual_rate, amort_months, freq)
    amount = expected if payment is None else _positive(payment, "payment", 1_000_000)
    if amount <= balance * rate:
        raise ValueError("payment does not cover interest; balance cannot be projected")
    if not 1 <= max_periods <= 2500:
        raise ValueError("schedule limit must be between 1 and 2500 payments")
    out = []
    for number in range(1, max_periods + 1):
        due = due_date(start, number, freq)
        if through is not None and due > through:
            break
        if balance <= 0.0000001:
            break
        opening = balance
        interest = opening * rate
        actual_payment = min(amount, opening + interest)
        principal = actual_payment - interest
        balance = max(opening - principal, 0.0)
        out.append(PaymentRow(number, due, opening, interest, actual_payment, principal, balance))
        if balance < 0.0000001:
            break
    return out


def project_balance(deal, as_of: date) -> dict:
    if deal.balance is None:
        raise ValueError("balance missing")
    if deal.balance_basis == "current":
        if deal.balance_date and deal.balance_date != as_of:
            raise ValueError("current balance date differs from review date; obtain the current statement balance")
        return {
            "balance": deal.balance,
            "basis": "as stated",
            "estimated": False,
            "payments_modelled": 0,
            "remaining_amort_months": deal.amort_months,
            "assumptions": [],
        }
    if deal.balance_basis != "original":
        raise ValueError("balance basis must be current or original")
    if deal.rate_type != "fixed":
        raise ValueError("original variable-rate balances need a current statement; historical rates are unknown")
    if not deal.closing_date or not deal.amort_months:
        raise ValueError("original balances need closing date and original amortization")
    if deal.amort_basis != "original":
        raise ValueError("original balance projection needs original, not remaining, amortization")
    frequency = payment_frequency(deal.frequency or "monthly")
    if frequency is None:
        raise ValueError("payment frequency not recognized")
    schedule = payment_schedule(
        deal.balance, deal.contract_rate, deal.amort_months, deal.closing_date,
        frequency, deal.payment, through=as_of,
    )
    current = schedule[-1].closing_balance if schedule else deal.balance
    elapsed = max(int(months_between(deal.closing_date, as_of)), 0)
    assumptions = [
        "Scheduled estimate: constant contract rate, no additional prepayments, and first payment after closing.",
        "Confirm the projected balance against the payout statement.",
    ]
    if not deal.frequency:
        assumptions.append("Monthly frequency assumed because the export did not state it.")
    return {
        "balance": round(current, 2),
        "basis": f"projected from the original {deal.balance:,.0f} over {len(schedule)} scheduled payments",
        "estimated": True,
        "payments_modelled": len(schedule),
        "remaining_amort_months": max(deal.amort_months - elapsed, 1),
        "assumptions": assumptions,
    }


def repayment_periods(balance, annual_rate, payment, frequency="monthly") -> float | None:
    balance = _positive(balance, "balance")
    payment = _positive(payment, "payment", 1_000_000)
    freq = payment_frequency(frequency)
    if freq is None:
        raise ValueError("payment frequency not recognized")
    rate = periodic_interest(annual_rate, PER_YEAR[freq])
    if rate == 0:
        return balance / payment
    if payment <= balance * rate:
        return None
    return -math.log1p(-balance * rate / payment) / math.log1p(rate)


def same_payment_projection(balance, old_rate, new_rate, amort_months, penalty, fees, payment=None, frequency="monthly"):
    freq = payment_frequency(frequency or "monthly")
    if freq is None:
        raise ValueError("payment frequency not recognized")
    amount = payment if payment is not None else scheduled_payment(balance, old_rate, amort_months, freq)
    before = repayment_periods(balance, old_rate, amount, freq)
    after = repayment_periods(balance + penalty + fees, new_rate, amount, freq)
    years = None if before is None or after is None else (before - after) / PER_YEAR[freq]
    return {
        "years_saved": round(years, 2) if years is not None else None,
        "payment": round(amount, 2),
        "frequency": freq,
        "periods_per_year": PER_YEAR[freq],
        "old_periods": round(before, 4) if before is not None else None,
        "new_periods": round(after, 4) if after is not None else None,
        "label": "Hypothetical lifetime projection: both rates assumed unchanged beyond their guaranteed terms.",
        "costs_financed": round(penalty + fees, 2),
    }


def interest_comparison(balance, old_rate, new_rate, amort_months, months, penalty, fees=0.0):
    if not 1 <= months <= 120:
        raise ValueError("comparison horizon must be between 1 and 120 months")
    old = _interest_path(balance, old_rate, amort_months, months)
    new = _interest_path(balance, new_rate, amort_months, months)
    costs = penalty + fees
    cumulative = 0.0
    break_even = None
    rows = []
    for month, (old_interest, new_interest) in enumerate(zip(old, new), 1):
        saving = old_interest - new_interest
        cumulative += saving
        net = cumulative - costs
        if break_even is None and net >= 0:
            break_even = month
        rows.append({
            "month": month,
            "old_interest": round(old_interest, 2),
            "new_interest": round(new_interest, 2),
            "interest_saved": round(saving, 2),
            "cumulative_interest_saved": round(cumulative, 2),
            "net_after_costs": round(net, 2),
        })
    return {
        "interest_saved": round(cumulative, 2),
        "net_benefit": round(cumulative - costs, 2),
        "break_even_months": break_even,
        "horizon_months": months,
        "penalty": round(penalty, 2),
        "fees": round(fees, 2),
        "monthly": rows,
        "basis": "Interest comparison with equal remaining amortization; penalty and fees paid in cash.",
    }


def wait_economics(balance, old_rate, new_rate, amort_months, horizon, wait_months, later_penalty, fees=0.0):
    if not 1 <= wait_months < horizon:
        raise ValueError("waiting must leave at least one month in the common comparison horizon")
    from ..ratewatch.ird import Mortgage, balance_after
    original = Mortgage(balance, old_rate, 60, date(2000, 1, 1), amort_months=amort_months)
    later_balance = balance_after(original, wait_months)
    if later_balance <= 0:
        return None
    remaining_amort = max(amort_months - wait_months, 1)
    result = interest_comparison(
        later_balance, old_rate, new_rate, remaining_amort,
        horizon - wait_months, later_penalty, fees,
    )
    old_early = sum(_interest_path(balance, old_rate, amort_months, wait_months))
    new_early = sum(_interest_path(balance, new_rate, amort_months, wait_months))
    result.update({
        "wait_months": wait_months,
        "balance_at_switch": round(later_balance, 2),
        "common_horizon_months": horizon,
        "early_interest_saving_forgone": round(old_early - new_early, 2),
        "basis": "Same end date as switching now; interest before the later switch cancels against staying.",
    })
    return result
