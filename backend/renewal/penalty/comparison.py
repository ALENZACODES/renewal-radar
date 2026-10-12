"""Comparison-rate selection for interest rate differential (IRD) estimates.

An IRD compares the contract rate with a lender's current rate for a term that
matches the time left on the mortgage. Lenders rarely publish a rate for every
month count, so a contract says how to pick one: the closest term, the next
shorter term, the next longer term, or (for some calculators) a straight-line
blend between neighbours. The choice can move a penalty by thousands of dollars,
so the rule is explicit here and every selection reports which terms it used.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping

D = Decimal


class TermRule(str, Enum):
    NEAREST = 'nearest'                  # ties go to the shorter term
    NEAREST_LONGER_ON_TIE = 'nearest_longer_on_tie'
    ROUND_DOWN = 'round_down'            # longest published term <= remaining
    ROUND_UP = 'round_up'                # shortest published term >= remaining
    INTERPOLATE = 'interpolate'          # linear between bracketing terms


@dataclass(frozen=True)
class ComparisonSelection:
    rate: D
    rule: TermRule
    remaining_months: int
    terms_used: tuple[int, ...]
    note: str

    def as_dict(self) -> dict:
        return {'rate': str(self.rate), 'rule': self.rule.value,
                'remaining_months': self.remaining_months,
                'terms_used': list(self.terms_used), 'note': self.note}


class NoComparisonRate(LookupError):
    """The rate table cannot support the requested rule for this remaining term."""


def _clean(table: Mapping[int, D]) -> dict[int, D]:
    clean: dict[int, D] = {}
    for term, rate in table.items():
        term = int(term)
        rate = D(str(rate))
        if term <= 0 or term > 360:
            raise ValueError(f'term {term} months is outside 1..360')
        if rate < 0 or rate > 30:
            raise ValueError(f'rate {rate} for {term} months is outside 0..30')
        clean[term] = rate
    if not clean:
        raise NoComparisonRate('rate table is empty')
    return dict(sorted(clean.items()))


def select_comparison_rate(table: Mapping[int, D], remaining_months: int,
                           rule: TermRule = TermRule.NEAREST) -> ComparisonSelection:
    """Pick the comparison rate for ``remaining_months`` from ``{term_months: rate}``."""
    if remaining_months <= 0:
        raise ValueError('remaining_months must be positive for an IRD comparison')
    rates = _clean(table)
    terms = list(rates)
    if remaining_months in rates:
        return ComparisonSelection(rates[remaining_months], rule, remaining_months,
                                   (remaining_months,), 'exact term published')
    shorter = [t for t in terms if t < remaining_months]
    longer = [t for t in terms if t > remaining_months]
    lo = shorter[-1] if shorter else None
    hi = longer[0] if longer else None

    if rule is TermRule.ROUND_DOWN:
        if lo is None:
            raise NoComparisonRate(f'no published term at or below {remaining_months} months')
        return ComparisonSelection(rates[lo], rule, remaining_months, (lo,),
                                   f'{lo}-month rate, the longest term not exceeding the time left')
    if rule is TermRule.ROUND_UP:
        if hi is None:
            raise NoComparisonRate(f'no published term at or above {remaining_months} months')
        return ComparisonSelection(rates[hi], rule, remaining_months, (hi,),
                                   f'{hi}-month rate, the shortest term covering the time left')
    if rule is TermRule.INTERPOLATE:
        if lo is None or hi is None:
            edge = lo if hi is None else hi
            return ComparisonSelection(rates[edge], rule, remaining_months, (edge,),
                                       'outside the published range; nearest edge used, not extrapolated')
        weight = D(remaining_months - lo) / D(hi - lo)
        rate = rates[lo] + (rates[hi] - rates[lo]) * weight
        return ComparisonSelection(rate.quantize(D('0.0001')), rule, remaining_months, (lo, hi),
                                   f'linear blend of {lo}- and {hi}-month rates')
    # nearest variants
    candidates = [t for t in (lo, hi) if t is not None]
    def distance(t: int) -> tuple[int, int]:
        tie_break = -t if rule is TermRule.NEAREST_LONGER_ON_TIE else t
        return abs(t - remaining_months), tie_break
    best = min(candidates, key=distance)
    return ComparisonSelection(rates[best], rule, remaining_months, (best,),
                               f'{best}-month rate, the closest published term')


def selection_spread(table: Mapping[int, D], remaining_months: int) -> dict[str, ComparisonSelection]:
    """Every rule the table can support, so a UI can show how much the rule matters."""
    out: dict[str, ComparisonSelection] = {}
    for rule in TermRule:
        try:
            out[rule.value] = select_comparison_rate(table, remaining_months, rule)
        except NoComparisonRate:
            continue
    return out
