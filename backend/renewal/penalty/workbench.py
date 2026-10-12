"""Date-driven penalty workbench.

Takes the facts a homeowner actually has (balance, contract rate, term start,
maturity, payout date, lender) plus a current posted-rate table and an optional
posted rate at funding, then:

1. converts dates into the remaining-term month count the contract uses,
2. picks the comparison rate with the lender's term rule,
3. works out the discount from the source the method calls for,
4. runs the Decimal penalty engine, and
5. reports how far the answer moves under every other defensible term rule.

Nothing is guessed: a missing input is reported, never filled in silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Mapping

from .comparison import NoComparisonRate, TermRule, select_comparison_rate, selection_spread
from .daycount import (MonthRounding, prorated_clawback, remaining_term,
                       three_month_interest_days, elapsed_months)
from .engine import calculate_penalty, money
from .methods import DiscountSource, MethodSpec, ThreeMonthBasis, spec_for
from .models import PenaltyInputs

D = Decimal


@dataclass(frozen=True)
class WorkbenchCase:
    lender: str
    balance: D
    contract_rate: D
    term_start: date
    maturity: date
    payout: date
    current_posted: Mapping[int, D]
    original_posted_rate: D | None = None
    contract_discount: D | None = None
    remaining_amortization_months: int | None = None
    privilege_available: D = D('0')
    privilege_applicable_to_full_payout: bool = False
    cashback: D = D('0')
    discharge_fee: D = D('0')
    is_open: bool = False
    rate_type: str = 'fixed'
    term_rule_override: TermRule | None = None
    month_rounding_override: MonthRounding | None = None


@dataclass(frozen=True)
class WorkbenchResult:
    spec: MethodSpec
    remaining_months: int
    remaining_detail: dict
    comparison: dict | None
    discount_pp: D | None
    discount_basis: str
    three_month_actual_days: D | None
    clawback: D
    estimate: dict
    sensitivity: list[dict] = field(default_factory=list)
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {'spec': self.spec.as_dict(), 'remaining_months': self.remaining_months,
                'remaining_detail': self.remaining_detail, 'comparison': self.comparison,
                'discount_pp': None if self.discount_pp is None else str(self.discount_pp),
                'discount_basis': self.discount_basis,
                'three_month_actual_days': None if self.three_month_actual_days is None
                else str(self.three_month_actual_days),
                'clawback': str(self.clawback), 'estimate': self.estimate,
                'sensitivity': self.sensitivity, 'warnings': list(self.warnings)}


def _discount(case: WorkbenchCase, spec: MethodSpec, warnings: list[str]) -> tuple[D | None, str]:
    if spec.discount_source is DiscountSource.NONE:
        return None, 'not used by this method'
    if case.contract_discount is not None:
        return D(case.contract_discount), 'contract'
    if case.original_posted_rate is not None:
        diff = D(case.original_posted_rate) - D(case.contract_rate)
        if diff < 0:
            warnings.append('Contract rate is above the posted rate at funding; discount treated as zero.')
            diff = D('0')
        if spec.discount_source is DiscountSource.CONTRACT:
            warnings.append('Discount derived from the posted rate at funding; the commitment may state a different figure.')
        return diff, 'original_posted_minus_contract'
    return None, 'missing'


def run_workbench(case: WorkbenchCase) -> WorkbenchResult:
    if case.payout < case.term_start:
        raise ValueError('payout date is before the term start')
    spec = spec_for(case.lender)
    rule = case.term_rule_override or spec.term_rule
    rounding = case.month_rounding_override or spec.month_rounding
    warnings: list[str] = []
    if not spec.verified:
        warnings.append('Comparison-term rule and month rounding are assumptions for this lender.')
    left = remaining_term(case.payout, case.maturity, rounding)
    term_months = elapsed_months(case.term_start, case.maturity)
    claw = money(prorated_clawback(D(case.cashback), max(1, term_months),
                                   elapsed_months(case.term_start, case.payout)))
    discount, discount_basis = _discount(case, spec, warnings)

    comparison = None
    comparison_rate: D | None = None
    if left.months > 0 and case.current_posted:
        try:
            sel = select_comparison_rate(case.current_posted, left.months, rule)
            comparison, comparison_rate = sel.as_dict(), sel.rate
        except NoComparisonRate as exc:
            warnings.append(f'No comparison rate: {exc}.')

    actual_days = None
    if spec.three_month_basis is ThreeMonthBasis.ACTUAL_DAYS:
        actual_days, _ = three_month_interest_days(D(case.balance), D(case.contract_rate), case.payout)
        actual_days = money(actual_days)

    base_inputs = PenaltyInputs(
        balance=D(case.balance), annual_rate=D(case.contract_rate), remaining_months=left.months,
        lender=case.lender, rate_type=case.rate_type, is_open=case.is_open,  # type: ignore[arg-type]
        comparison_posted_rate=comparison_rate, original_posted_rate=case.original_posted_rate,
        documented_discount=discount, original_term_months=term_months,
        remaining_amortization_months=case.remaining_amortization_months,
        privilege_available=D(case.privilege_available),
        privilege_applicable_to_full_payout=case.privilege_applicable_to_full_payout,
        cashback_clawback=claw, discharge_fee=D(case.discharge_fee),
        comparison_rate_source=f'posted table, rule={rule.value}')
    estimate = calculate_penalty(base_inputs).as_dict()

    sensitivity: list[dict] = []
    if left.months > 0 and case.current_posted:
        for name, sel in selection_spread(case.current_posted, left.months).items():
            alt = calculate_penalty(replace(base_inputs, comparison_posted_rate=sel.rate))
            sensitivity.append({'rule': name, 'comparison_rate': str(sel.rate),
                                'terms_used': list(sel.terms_used),
                                'total_estimate': None if alt.total_estimate is None
                                else str(alt.total_estimate),
                                'controlling_method': alt.controlling_method})
    totals = [D(s['total_estimate']) for s in sensitivity if s['total_estimate'] is not None]
    if totals and max(totals) - min(totals) >= D('500'):
        warnings.append(f'The comparison-term rule alone moves the estimate by ${money(max(totals) - min(totals))}.')
    return WorkbenchResult(spec, left.months, left.as_dict(), comparison, discount, discount_basis,
                           actual_days, claw, estimate, sensitivity, tuple(warnings))
