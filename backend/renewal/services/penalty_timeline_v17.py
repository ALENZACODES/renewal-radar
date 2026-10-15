"""Month-by-month exit-cost scenarios using the existing audited penalty engine."""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.mortgage_math import simulate
from ..penalty import PenaltyInputs, calculate_penalty
from ..penalty.models import Method


class RateBucket(BaseModel):
    model_config = ConfigDict(extra='forbid')
    months: int = Field(ge=1, le=120, strict=True)
    rate: Decimal = Field(ge=0, le=30)


class PenaltyTimelineRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    balance: Decimal = Field(gt=0, le=100000000)
    contract_rate: Decimal = Field(ge=0, le=30)
    remaining_months: int = Field(ge=0, le=120, strict=True)
    amortization_months: int = Field(ge=1, le=480, strict=True)
    start_date: date = Field(default_factory=date.today)
    comparison_rate: Decimal | None = Field(default=None, ge=0, le=30)
    discount: Decimal | None = Field(default=None, ge=0, le=30)
    fees: Decimal = Field(default=Decimal('0'), ge=0, le=1000000)
    rate_type: Literal['fixed', 'variable'] = 'fixed'
    frequency: Literal['monthly', 'semi-monthly', 'biweekly', 'weekly', 'accelerated-biweekly', 'accelerated-weekly'] = 'monthly'
    method: Literal['simple_differential', 'posted_minus_discount', 'present_value', 'undocumented'] = 'undocumented'
    ladder: list[RateBucket] = Field(default_factory=list, max_length=12)
    bucket_rule: Literal['ceiling', 'nearest'] = 'ceiling'

    @model_validator(mode='after')
    def consistent_inputs(self):
        if self.amortization_months < self.remaining_months:
            raise ValueError('Remaining amortization cannot be shorter than the modelled term')
        if not 1900 <= self.start_date.year <= 2090:
            raise ValueError('Projection start date must be between 1900 and 2090')
        if len({bucket.months for bucket in self.ladder}) != len(self.ladder):
            raise ValueError('Comparison term buckets must be unique')
        return self


def month_date(start: date, offset: int) -> date:
    index = start.year * 12 + start.month - 1 + offset
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def select_bucket(ladder: list[RateBucket], remaining: int, rule: str) -> RateBucket | None:
    if remaining == 0 or not ladder:
        return None
    if rule == 'nearest':
        return min(ladder, key=lambda item: (abs(item.months - remaining), -item.months))
    candidates = [item for item in ladder if item.months >= remaining]
    return min(candidates, key=lambda item: item.months) if candidates else None


def penalty_timeline(request: PenaltyTimelineRequest) -> dict:
    p = request
    ledger = simulate(float(p.balance), float(p.contract_rate), p.amortization_months,
                      max(1, p.remaining_months), p.frequency, p.rate_type)
    seed = PenaltyInputs(balance=p.balance, annual_rate=p.contract_rate,
                         remaining_months=p.remaining_months, lender='generic',
                         rate_type=p.rate_type, documented_discount=p.discount,
                         remaining_amortization_months=p.amortization_months,
                         other_fee=p.fees, explicit_method=Method(p.method),
                         comparison_rate_source='User-entered static comparison snapshot; not a future quote')
    points = []
    transitions = []
    previous_bucket = None
    balance = p.balance
    ledger_index = 0
    for elapsed in range(p.remaining_months + 1):
        while ledger_index < len(ledger['schedule']) and ledger['schedule'][ledger_index]['month'] <= elapsed:
            balance = Decimal(str(ledger['schedule'][ledger_index]['balance']))
            ledger_index += 1
        remaining = p.remaining_months - elapsed
        bucket = select_bucket(p.ladder, remaining, p.bucket_rule)
        comparison = bucket.rate if bucket else (None if p.ladder else p.comparison_rate)
        if balance <= 0:
            result = {'status': 'no_charge_modelled', 'core_charge': '0.00',
                      'three_month_interest': '0.00', 'interest_rate_differential': '0.00',
                      'total_estimate': str(p.fees), 'additional_fees': str(p.fees),
                      'controlling_method': 'none', 'missing_fields': [],
                      'formulas': ['No mortgage principal remains in the projection.'],
                      'warnings': ['Separate lender fees may still apply.'], 'audit': {}}
        else:
            result = calculate_penalty(replace(seed, balance=balance, remaining_months=remaining,
                                      comparison_posted_rate=comparison,
                                      remaining_amortization_months=max(1, p.amortization_months - elapsed))).as_dict()
        point = {'month': elapsed, 'date': month_date(p.start_date, elapsed).isoformat(),
                 'remaining_months': remaining, 'balance': str(balance),
                 'bucket_months': bucket.months if bucket else None,
                 'comparison_rate': str(comparison) if comparison is not None else None,
                 'penalty': result}
        points.append(point)
        current_bucket = bucket.months if bucket else None
        if elapsed and remaining and current_bucket != previous_bucket:
            transitions.append({'month': elapsed, 'date': point['date'], 'remaining_months': remaining,
                                'from_bucket_months': previous_bucket, 'to_bucket_months': current_bucket,
                                'comparison_rate': point['comparison_rate']})
        previous_bucket = current_bucket
    return {'points': points, 'transitions': transitions, 'method': p.method,
            'start_date': p.start_date.isoformat(), 'modelled_maturity': points[-1]['date'],
            'regular_payment': str(ledger['regular_payment']), 'frequency': p.frequency,
            'ladder': [bucket.model_dump(mode='json') for bucket in sorted(p.ladder, key=lambda x: x.months)],
            'bucket_rule': p.bucket_rule,
            'assumptions': [
                'Illustrative exit costs, not a lender payout statement or recommendation to break a mortgage.',
                'Entered comparison rates are held constant by term bucket; future market rates are unknown.',
                'Principal follows the existing Canadian mortgage simulation with scheduled payments and no extra prepayments.',
                'Dates are calendar-month anniversaries, not lender daily-interest settlement dates.',
                'Present-value IRD retains the existing illustrative monthly-compounding approximation, which differs from some contracts.',
                'A missing methodology, comparison rate or required discount leaves the final charge unknown.',
            ],
            'source_url': 'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html'}
