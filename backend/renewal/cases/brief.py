"""Assemble a renewal decision brief from confirmed mortgage facts.

Inputs are the fields the homeowner confirmed (usually from statement reading).
The brief answers three questions with provenance for every number:

1. How does the renewal offer compare with today's posted market?
2. What would it cost to break the mortgage today instead of waiting?
3. What is still missing before any of this can be relied on?

Nothing is estimated from missing inputs. A missing fact produces a ``missing``
entry and the dependent section is skipped, never filled with a default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from ..domain.mortgage_math import scheduled_payment
from ..penalty.daycount import add_months
from ..penalty.workbench import WorkbenchCase, run_workbench
from ..rates.series import RateBook

D = Decimal
CENT = D('0.01')


@dataclass(frozen=True)
class ConfirmedFacts:
    lender: str
    balance: D
    rate_pct: D
    maturity_date: date
    term_months: int
    amortization_months: int | None = None
    renewal_rate_pct: D | None = None
    renewal_term_months: int = 60
    rate_type: str = 'fixed'
    frequency: str = 'monthly'
    contract_discount: D | None = None
    cashback: D = D('0')

    def __post_init__(self) -> None:
        if self.balance <= 0:
            raise ValueError('balance must be positive')
        if not D(0) <= self.rate_pct <= D(30):
            raise ValueError('rate must be 0 to 30')
        if not 6 <= self.term_months <= 120:
            raise ValueError('term must be 6 to 120 months')
        if self.amortization_months is not None and not self.term_months <= self.amortization_months <= 480:
            raise ValueError('amortization must be at least the term and at most 480 months')
        if self.renewal_rate_pct is not None and not D(0) <= self.renewal_rate_pct <= D(30):
            raise ValueError('renewal rate must be 0 to 30')


@dataclass
class Brief:
    as_of: date
    days_to_maturity: int
    funded_on: date
    offer: dict | None = None
    break_today: dict | None = None
    missing: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {'as_of': self.as_of.isoformat(), 'days_to_maturity': self.days_to_maturity,
                'funded_on': self.funded_on.isoformat(), 'offer': self.offer,
                'break_today': self.break_today, 'missing': self.missing,
                'cautions': self.cautions, 'sources': self.sources,
                'notice': 'Estimates only. Ask the lender for a dated payout statement and written offer.'}


def _money(x: float | D) -> str:
    return str(D(str(x)).quantize(CENT, rounding=ROUND_HALF_UP))


def _offer_section(f: ConfirmedFacts, book: RateBook, today: date, brief: Brief) -> None:
    if f.renewal_rate_pct is None:
        brief.missing.append('renewal offer rate (from the renewal letter)')
        return
    if f.amortization_months is None:
        brief.missing.append('remaining amortization')
        return
    posted = book.posted_at(f.lender, f.renewal_term_months, today)
    if posted is None:
        brief.missing.append(f'a posted {f.renewal_term_months}-month rate within the last 120 days')
        return
    brief.sources.append({'use': 'posted rate today', **posted.as_dict()})
    remaining = max(1, f.amortization_months - f.term_months + max(0, (f.maturity_date - today).days // 30))
    remaining = min(remaining, f.amortization_months)
    pay_offer = scheduled_payment(float(f.balance), float(f.renewal_rate_pct), remaining, f.frequency, f.rate_type)
    pay_posted = scheduled_payment(float(f.balance), float(posted.rate), remaining, f.frequency, f.rate_type)
    discount = posted.rate - f.renewal_rate_pct
    brief.offer = {
        'renewal_rate_pct': str(f.renewal_rate_pct), 'posted_rate_pct': str(posted.rate),
        'discount_from_posted_pp': str(discount), 'posted_is_proxy': posted.proxy,
        'payment_at_offer': _money(pay_offer), 'payment_at_posted': _money(pay_posted),
        'amortization_months_used': remaining, 'frequency': f.frequency,
    }
    if discount < D('0.50'):
        brief.cautions.append('The renewal offer is less than 0.50 points below posted; lenders often '
                              'discount more for borrowers who ask or have a competing offer.')
    if posted.proxy:
        brief.cautions.append('Posted rate is the Bank of Canada chartered-bank figure, not this lender\'s own.')


def _discount(derived: D | None, printed: D | None) -> str | None:
    """Prefer the discount derived from posted history; fall back to the printed one."""
    value = derived if derived is not None else printed
    return None if value is None else str(value)


def _break_section(f: ConfirmedFacts, book: RateBook, today: date, funded: date, brief: Brief) -> None:
    if today >= f.maturity_date:
        brief.cautions.append('The term has matured; no prepayment charge should apply to a renewal or switch.')
        return
    original = book.posted_at(f.lender, f.term_months, funded)
    if original is not None:
        brief.sources.append({'use': 'posted rate at funding', **original.as_dict()})
    elif f.contract_discount is None:
        brief.missing.append(f'posted {f.term_months}-month rate at funding ({funded.isoformat()}) or the '
                             'discount printed on the commitment')
    table = book.table_at(f.lender, today)
    for term, hit in table.items():
        brief.sources.append({'use': f'posted {term}-month rate today', **hit.as_dict()})
    result = run_workbench(WorkbenchCase(
        lender=f.lender, balance=f.balance, contract_rate=f.rate_pct, term_start=funded,
        maturity=f.maturity_date, payout=today, current_posted={t: h.rate for t, h in table.items()},
        original_posted_rate=None if original is None else original.rate,
        contract_discount=f.contract_discount, cashback=f.cashback, rate_type=f.rate_type,
        remaining_amortization_months=f.amortization_months))
    est = result.estimate
    brief.break_today = {
        'remaining_months': result.remaining_months, 'status': est['status'],
        'three_month_interest': est['three_month_interest'],
        'interest_rate_differential': est['interest_rate_differential'],
        'total_estimate': est['total_estimate'], 'controlling_method': est['controlling_method'],
        'comparison': result.comparison, 'discount_pp': _discount(result.discount_pp, f.contract_discount),
        'sensitivity': result.sensitivity,
    }
    brief.missing.extend(m for m in est['missing_fields'] if m not in brief.missing)
    brief.cautions.extend(w for w in result.warnings if w not in brief.cautions)


def build_brief(f: ConfirmedFacts, book: RateBook, today: date) -> Brief:
    funded = add_months(f.maturity_date, -f.term_months)
    if funded > today:
        raise ValueError('maturity minus term is in the future; check the term length')
    brief = Brief(today, (f.maturity_date - today).days, funded)
    _offer_section(f, book, today, brief)
    _break_section(f, book, today, funded, brief)
    if 0 <= brief.days_to_maturity <= 120:
        brief.cautions.append('Within 120 days of maturity: most lenders will hold a rate for a switch now.')
    return brief
