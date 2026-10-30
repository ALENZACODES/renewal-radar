"""Lender method specifications layered on top of the method profiles.

``profiles.py`` says *which* IRD family a lender uses. A method spec adds the
contract details that family needs: how the comparison term is chosen, how part
months are counted, how three-month interest is measured, and where the
discount comes from. Specs marked ``verified=False`` are conservative defaults
that the UI must present as assumptions, not as the lender's rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .comparison import TermRule
from .daycount import MonthRounding
from .profiles import profile_for


class DiscountSource(str, Enum):
    CONTRACT = 'contract'                 # printed on the mortgage commitment
    ORIGINAL_POSTED = 'original_posted'   # posted rate at funding minus contract rate
    NONE = 'none'                         # simple differential, no discount used


class ThreeMonthBasis(str, Enum):
    QUARTER_YEAR = 'quarter_year'         # balance x rate x 3/12
    ACTUAL_DAYS = 'actual_days'           # balance x rate x days / 365


@dataclass(frozen=True)
class MethodSpec:
    lender: str
    term_rule: TermRule
    month_rounding: MonthRounding
    three_month_basis: ThreeMonthBasis
    discount_source: DiscountSource
    verified: bool
    basis_note: str

    def as_dict(self) -> dict:
        return {'lender': self.lender, 'term_rule': self.term_rule.value,
                'month_rounding': self.month_rounding.value,
                'three_month_basis': self.three_month_basis.value,
                'discount_source': self.discount_source.value,
                'verified': self.verified, 'basis_note': self.basis_note}


_DEFAULT = MethodSpec('generic', TermRule.NEAREST, MonthRounding.UP,
                      ThreeMonthBasis.QUARTER_YEAR, DiscountSource.NONE, False,
                      'Conservative default: closest published term, part months rounded up.')

# Only the shape of each method is recorded here. The comparison-term rules are
# the ones described in each lender's public prepayment pages at the profile
# version date; anything not stated publicly stays unverified.
SPECS: dict[str, MethodSpec] = {
    'generic': _DEFAULT,
    'rbc': MethodSpec('rbc', TermRule.NEAREST, MonthRounding.UP, ThreeMonthBasis.QUARTER_YEAR,
                      DiscountSource.ORIGINAL_POSTED, False,
                      'Posted-minus-discount family; comparison term selection to confirm on payout statement.'),
    'rbc_pv': MethodSpec('rbc_pv', TermRule.NEAREST, MonthRounding.UP, ThreeMonthBasis.QUARTER_YEAR,
                         DiscountSource.ORIGINAL_POSTED, False,
                         'Present-value family; discounting conventions are approximated.'),
    'td': MethodSpec('td', TermRule.NEAREST, MonthRounding.UP, ThreeMonthBasis.QUARTER_YEAR,
                     DiscountSource.ORIGINAL_POSTED, False,
                     'Posted-minus-discount family using the closest term.'),
    'scotia': MethodSpec('scotia', TermRule.NEAREST, MonthRounding.UP, ThreeMonthBasis.QUARTER_YEAR,
                         DiscountSource.ORIGINAL_POSTED, False,
                         'Present-value family; payment timing simplified.'),
    'cibc': MethodSpec('cibc', TermRule.NEAREST, MonthRounding.UP, ThreeMonthBasis.QUARTER_YEAR,
                       DiscountSource.CONTRACT, False,
                       'Discount add-back family; discount should come from the commitment.'),
}


def spec_for(lender: str) -> MethodSpec:
    """Spec for a lender code, falling back to the conservative default."""
    code = profile_for(lender).code
    spec = SPECS.get(code)
    if spec is None:
        return MethodSpec(code, _DEFAULT.term_rule, _DEFAULT.month_rounding,
                          _DEFAULT.three_month_basis, _DEFAULT.discount_source, False,
                          _DEFAULT.basis_note)
    return spec


def all_specs() -> list[dict]:
    return [s.as_dict() for s in SPECS.values()]
