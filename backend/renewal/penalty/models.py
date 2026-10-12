"""Explicitly typed Canadian prepayment-penalty domain objects.

Money and rates are Decimal to avoid binary-float arithmetic. Rate inputs are
percentage points, e.g. 5.25 means 5.25%, never 0.0525.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal

D = Decimal
class Method(str, Enum):
    SIMPLE = 'simple_differential'
    POSTED_DISCOUNT = 'posted_minus_discount'
    CIBC = 'cibc_discount_addback'
    PRESENT_VALUE = 'present_value'
    UNKNOWN = 'undocumented'

@dataclass(frozen=True)
class LenderProfile:
    code: str
    name: str
    method: Method
    source_url: str
    version: str
    source_verified: bool
    notes: str = ''
    three_month_days: int | None = None
    comparison_term_rule: str = 'lender_specific'
    limitations: tuple[str, ...] = ()

@dataclass(frozen=True)
class PenaltyInputs:
    balance: D
    annual_rate: D
    remaining_months: int
    lender: str = 'generic'
    rate_type: Literal['fixed','variable'] = 'fixed'
    is_open: bool = False
    comparison_posted_rate: D | None = None
    original_posted_rate: D | None = None
    documented_discount: D | None = None
    original_term_months: int | None = None
    elapsed_term_months: int | None = None
    remaining_amortization_months: int | None = None
    monthly_payment: D | None = None
    payout_amount: D | None = None
    privilege_available: D = D('0')
    privilege_applicable_to_full_payout: bool = False
    cashback_clawback: D = D('0')
    discharge_fee: D = D('0')
    administration_fee: D = D('0')
    reinvestment_fee: D = D('0')
    other_fee: D = D('0')
    comparison_rate_source: str | None = None
    contract_version: str | None = None
    three_month_basis: Literal['90_days','quarter_year'] = 'quarter_year'
    explicit_method: Method | None = None

@dataclass(frozen=True)
class PenaltyResult:
    lender: str
    profile_version: str
    method: str
    penalty_base: D
    three_month_interest: D
    interest_rate_differential: D | None
    core_charge: D | None
    additional_fees: D
    total_estimate: D | None
    controlling_method: str
    status: Literal['estimate','floor_only','no_charge_modelled','insufficient_evidence']
    formulas: tuple[str,...] = ()
    missing_fields: tuple[str,...] = ()
    warnings: tuple[str,...] = ()
    source_url: str = ''
    audit: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        def convert(value):
            if isinstance(value, D): return str(value)
            if isinstance(value, tuple): return [convert(v) for v in value]
            if isinstance(value, dict): return {k:convert(v) for k,v in value.items()}
            return value
        return {k:convert(v) for k,v in vars(self).items()}
