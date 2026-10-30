"""All money is CAD and rates are percentages (5.49, not 0.0549)."""
from __future__ import annotations
from typing import Literal
from datetime import date
from pydantic import BaseModel, Field, ConfigDict, model_validator

RateType = Literal['fixed','variable']
Frequency = Literal['monthly','semi-monthly','biweekly','weekly','accelerated-biweekly','accelerated-weekly']

class Mortgage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    balance: float = Field(default=480000,gt=0,le=100000000)
    offered_rate: float = Field(default=5.49,ge=0,le=30)
    current_rate: float = Field(default=4.19,ge=0,le=30)
    amortization_months: int = Field(default=228,ge=1,le=480)
    term_months: int = Field(default=36,ge=1,le=120)
    maturity_date: str = '2027-03-01'
    frequency: Frequency = 'monthly'
    rate_type: RateType = 'fixed'
    lender: str = Field(default='Maple Bank (illustrative)',max_length=120)
    insurance_status: Literal['insured','uninsured','unknown'] = 'uninsured'
    existing_lender_federally_regulated: bool | None = True
    new_lender_federally_regulated: bool | None = True
    standalone: bool | None = True
    combined_loan_plan: bool | None = False
    amortization_increase: bool = False
    cash_out: float = Field(default=0,ge=0,le=100000000)
    fees_financed: float = Field(default=0,ge=0,le=1000000)
    original_loan_stress_tested: bool | None = None
    current_ltv: float | None = Field(default=None,ge=0,le=3)
    original_posted_rate: float | None = Field(default=None,ge=0,le=30)
    original_contract_discount: float | None = Field(default=None,ge=0,le=20)
    remaining_old_term_months: int = Field(default=0,ge=0,le=120)
    prepayment_privilege_percent: float | None = Field(default=None,ge=0,le=100)
    origination_balance: float | None = Field(default=None,gt=0,le=100000000)

    @model_validator(mode='after')
    def check_dates(self):
        date.fromisoformat(self.maturity_date)
        return self

class Offer(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    rate: float = Field(ge=0,le=30)
    rate_type: RateType = 'fixed'
    term_months: int = Field(default=36,ge=1,le=120)
    amortization_months: int | None = Field(default=None,ge=1,le=480)
    fees: float = Field(default=0,ge=0,le=1000000)
    fee_credit: float = Field(default=0,ge=0,le=1000000)
    type: Literal['hypothetical','personalized','published'] = 'hypothetical'
    source_url: str | None = None
    annual_prepayment: float = Field(default=0,ge=0,le=10000000)
    monthly_extra: float = Field(default=0,ge=0,le=100000)
    variable_path_bps: list[int] = Field(default_factory=list,max_length=120)
    fixed_payment_variable: bool = False

class AnalyzeRequest(BaseModel):
    mortgage: Mortgage
    offers: list[Offer] = Field(default_factory=list,max_length=12)
    horizon_months: int = Field(default=36,ge=1,le=120)
    discount_rate: float = Field(default=4.0,ge=0,le=20)
    penalty: PenaltyRequest | None = None

class PenaltyRequest(BaseModel):
    balance: float = Field(gt=0,le=1e8)
    current_rate: float = Field(ge=0,le=30)
    rate_type: RateType = 'fixed'
    remaining_term_months: int = Field(ge=0,le=120)
    comparison_rate: float | None = Field(default=None,ge=0,le=30)
    original_posted_rate: float | None = Field(default=None,ge=0,le=30)
    original_discount: float | None = Field(default=None,ge=0,le=20)
    contract_method: Literal['simple','posted-discount','unknown'] = 'unknown'
    is_open: bool = False

class FieldEvidence(BaseModel):
    value: float | str | None = None
    page: int | None = None
    excerpt: str = ''
    confidence: Literal['high','medium','low'] = 'low'

class Extraction(BaseModel):
    fields: dict[str,FieldEvidence]
    pages: int
    filename: str
    warnings: list[str] = Field(default_factory=list)
    provider: str = 'deterministic'
    preview: list[dict] = Field(default_factory=list)

class CaseCreate(BaseModel):
    mortgage: Mortgage
    offers: list[Offer] = Field(default_factory=list,max_length=12)
    title: str = Field(default='My renewal plan',max_length=100)
    workspace_id: str = Field(..., min_length=1, max_length=64)

class ShareRequest(BaseModel):
    expires_hours: int = Field(default=24,ge=1,le=168)

class CaseTokenMint(BaseModel):
    scopes: list[str] = Field(..., min_length=1, max_length=8)
    ttl_seconds: int = Field(default=3600, ge=60, le=604800)

class NegotiationRequest(BaseModel):
    mortgage: Mortgage
    competing_rate: float = Field(ge=0,le=30)
    competing_lender: str = Field(default='a competing lender',max_length=120)
    competitor_offer_verified: bool = False
    goals: Literal['lower_payment','lower_interest','flexibility'] = 'lower_interest'
    notes: str = Field(default='',max_length=2000)
