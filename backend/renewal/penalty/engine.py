"""Deterministic penalty calculation with explicit accuracy limits and audit trail.

All computations use Decimal and avoid fabricating the comparison rate.
The lender's dated written payout statement remains authoritative.
"""
from __future__ import annotations
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
from .models import D, Method, PenaltyInputs, PenaltyResult
from .profiles import profile_for

CENT = D('0.01')
def money(x: D) -> D:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)

def _validate(p: PenaltyInputs) -> None:
    if p.balance <= 0 or p.balance > D('1000000000'):
        raise ValueError('balance must be positive and below one billion')
    if p.annual_rate < 0 or p.annual_rate > 30:
        raise ValueError('annual_rate must be a percentage from 0 to 30')
    if p.remaining_months < 0 or p.remaining_months > 360:
        raise ValueError('remaining_months must be between 0 and 360')
    if p.rate_type not in ('fixed','variable'):
        raise ValueError('rate_type must be fixed or variable')
    for name in ('comparison_posted_rate','original_posted_rate','documented_discount'):
        val=getattr(p,name)
        if val is not None and (val < 0 or val > 30):
            raise ValueError(name+' must be 0..30 percentage points')
    for name in ('privilege_available','cashback_clawback','discharge_fee',
                 'administration_fee','reinvestment_fee','other_fee'):
        if getattr(p,name) < 0:
            raise ValueError(name+' cannot be negative')
    if p.payout_amount is not None and (p.payout_amount <= 0 or p.payout_amount > p.balance):
        raise ValueError('payout_amount must be positive and <= balance')
    if p.remaining_amortization_months is not None and p.remaining_amortization_months < p.remaining_months:
        raise ValueError('amortization cannot be shorter than remaining term for PV model')

def _payment(principal: D, monthly_rate: D, periods: int) -> D:
    if periods <= 0: return principal
    if monthly_rate == 0: return principal / D(periods)
    factor=(D('1')+monthly_rate)**periods
    return principal*monthly_rate*factor/(factor-D('1'))

def _pv_ird(principal: D, old_pct: D, comparison_pct: D,
            term_months: int, amort_months: int) -> D:
    """Difference of PV payment cashflows, including terminal balance.

This is a clearly labeled approximation, not a reproduction of a lender's
proprietary daily-interest, effective-rate, payment-adjustment conventions.
"""
    old_r=old_pct/D('1200')
    new_r=comparison_pct/D('1200')
    old_payment=_payment(principal,old_r,amort_months)
    new_payment=_payment(principal,new_r,amort_months)
    old_balance=principal
    new_balance=principal
    old_pv=D('0')
    new_pv=D('0')
    discount=D('1')
    for _ in range(term_months):
        discount *= D('1')+new_r
        old_interest=old_balance*old_r
        new_interest=new_balance*new_r
        old_balance=max(D('0'),old_balance+old_interest-old_payment)
        new_balance=max(D('0'),new_balance+new_interest-new_payment)
        old_pv += old_payment/discount
        new_pv += new_payment/discount
    old_pv+=old_balance/discount
    new_pv+=new_balance/discount
    return max(D('0'),old_pv-new_pv)

def calculate_penalty(p: PenaltyInputs) -> PenaltyResult:
    _validate(p)
    profile=profile_for(p.lender)
    method=p.explicit_method or profile.method
    fees=sum((p.cashback_clawback,p.discharge_fee,p.administration_fee,
              p.reinvestment_fee,p.other_fee),D('0'))
    amount=p.payout_amount if p.payout_amount is not None else p.balance
    warnings=[]
    if p.privilege_available and not p.privilege_applicable_to_full_payout:
        warnings.append('Annual privilege not assumed deductible from a full payout; confirm with lender.')
    privileged=min(p.privilege_available,amount) if p.privilege_applicable_to_full_payout else D('0')
    base=amount-privileged
    if not profile.source_verified:
        warnings.append('Lender-specific method has not been independently verified.')
    if profile.limitations: warnings.extend(profile.limitations)
    formulas=[]
    audit={'profile':profile.code,'version':profile.version,
           'comparison_rate_source':p.comparison_rate_source,'contract_version':p.contract_version,
           'rate_units':'percentage_points','rounding':'HALF_UP cents at output'}
    if p.is_open or p.remaining_months == 0:
        return PenaltyResult(profile.name,profile.version,method.value, money(base),D('0'),D('0'),D('0'),
          money(fees),money(fees),'none','no_charge_modelled',
          ('No prepayment penalty modelled for open or matured mortgage.',),(),tuple(warnings),profile.source_url,audit)
    floor_rate=p.annual_rate
    if profile.code=='cibc' and p.rate_type=='fixed':
        if p.documented_discount is not None:
            floor_rate+=p.documented_discount
            formulas.append('CIBC contract variant: three-month rate = contract rate + documented discount.')
        else:
            warnings.append('CIBC discount unavailable: three-month floor may be understated.')
    factor=D('90')/D('365') if p.three_month_basis=='90_days' else D('0.25')
    three=base*floor_rate/D('100')*factor
    formulas.append(f'Three-month interest = penalty base x {floor_rate}% x {factor}.')
    if p.rate_type == 'variable':
        return PenaltyResult(profile.name,profile.version,method.value,money(base),money(three),None,
          money(three),money(fees),money(three+fees),'3_months','estimate',tuple(formulas),(),
          tuple(warnings+['Variable closed penalty model uses three-month proxy; contract may differ.']),profile.source_url,audit)
    required=[]
    if method==Method.UNKNOWN:
        required.append('verified lender-specific methodology')
    if p.comparison_posted_rate is None:
        required.append('current comparison rate for applicable remaining-term bucket')
    if method in (Method.POSTED_DISCOUNT,Method.CIBC,Method.PRESENT_VALUE) and p.documented_discount is None:
        required.append('documented original rate discount')
    if method==Method.PRESENT_VALUE and p.remaining_amortization_months is None:
        required.append('remaining amortization for PV model')
    if required:
        warnings.append('Do not quote floor as final penalty: IRD may be higher.')
        return PenaltyResult(profile.name,profile.version,method.value,money(base),money(three),None,None,
            money(fees),None,'undetermined','floor_only',tuple(formulas),tuple(required),
            tuple(warnings),profile.source_url,audit)
    if method==Method.SIMPLE:
        adjusted=p.comparison_posted_rate
        ird=base*max(D('0'),p.annual_rate-adjusted)/D('100')*D(p.remaining_months)/D('12')
        formulas.append('Simple IRD = base x max(contract - comparison, 0) x remaining months / 1200.')
    elif method==Method.POSTED_DISCOUNT:
        adjusted=max(D('0'),p.comparison_posted_rate-p.documented_discount)
        ird=base*max(D('0'),p.annual_rate-adjusted)/D('100')*D(p.remaining_months)/D('12')
        formulas.append('Posted-discount IRD proxy = base x max(contract - (posted - discount), 0) x months / 1200.')
    elif method==Method.CIBC:
        adjusted=p.comparison_posted_rate
        ird=base*max(D('0'),p.annual_rate+p.documented_discount-adjusted)/D('100')*D(p.remaining_months)/D('12')
        formulas.append('CIBC illustrative IRD = base x max(contract + discount - comparison, 0) x months / 1200.')
    else:
        adjusted=max(D('0'),p.comparison_posted_rate-p.documented_discount)
        ird=_pv_ird(base,p.annual_rate,adjusted,p.remaining_months,p.remaining_amortization_months)
        formulas.append('PV proxy = PV(contract payment stream + terminal balance) - PV(comparison stream + terminal balance).')
        warnings.append('PV model is illustrative: lender timing, compounding and contract conventions differ.')
    core=max(three,ird)
    audit['adjusted_comparison_pct']=str(adjusted)
    return PenaltyResult(profile.name,profile.version,method.value,money(base),money(three),money(ird),
       money(core),money(fees),money(core+fees),'ird' if ird>three else '3_months',
       'estimate',tuple(formulas),(),tuple(warnings+['Request the dated written lender payout statement.']),profile.source_url,audit)

def forecast_penalty(p: PenaltyInputs, months_ahead: int, expected_posted_rates: list[D] | None=None) -> list[dict]:
    if months_ahead < 0 or months_ahead > min(120,p.remaining_months):
        raise ValueError('months_ahead outside remaining mortgage term')
    if expected_posted_rates is not None and len(expected_posted_rates)<months_ahead+1:
        raise ValueError('rate path must include today and each future month')
    out=[]
    for i in range(months_ahead+1):
        comparison=p.comparison_posted_rate if expected_posted_rates is None else expected_posted_rates[i]
        next_p=replace(p,remaining_months=max(0,p.remaining_months-i),comparison_posted_rate=comparison)
        result=calculate_penalty(next_p)
        out.append({'month':i,'comparison_rate':str(comparison) if comparison is not None else None,
                   'penalty':result.as_dict()})
    return out

def optimize_privilege(p: PenaltyInputs, available: D, full_payout_allowed: bool) -> dict:
    without=calculate_penalty(replace(p,privilege_available=D('0')))
    with_privilege=calculate_penalty(replace(p,privilege_available=available,
                                             privilege_applicable_to_full_payout=full_payout_allowed))
    savings=None
    if without.total_estimate is not None and with_privilege.total_estimate is not None:
        savings=money(without.total_estimate-with_privilege.total_estimate)
    return {'before':without.as_dict(),'after':with_privilege.as_dict(),
       'modelled_penalty_reduction':str(savings) if savings is not None else None,
       'critical_warning':'Confirm whether the prepayment privilege can be applied immediately before full discharge; some contracts prohibit this.'}
