"""Auditable Canadian mortgage mathematics.

Fixed-rate nominal APR compounded semi-annually, including monthly payments:
periodic_rate = (1 + APR / 2) ** (2 / payments_per_year) - 1.
Variable calculations use nominal APR compounded monthly by default; actual
lender contracts may differ. Outputs are estimates, not payout statements.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from math import isfinite
from typing import Iterable

PER_YEAR = {'monthly':12,'semi-monthly':24,'biweekly':26,'weekly':52,
            'accelerated-biweekly':26,'accelerated-weekly':52}


def periodic_rate(rate_percent: float, payments_per_year: int=12, rate_type: str='fixed') -> float:
    if not 0 <= rate_percent <= 30 or payments_per_year not in (12,24,26,52):
        raise ValueError('Invalid rate or payment frequency')
    r = rate_percent / 100
    if rate_type == 'fixed':
        return (1 + r/2) ** (2/payments_per_year) - 1
    if rate_type == 'variable':
        return (1 + r/12) ** (12/payments_per_year) - 1
    raise ValueError('Unknown rate type')


def scheduled_payment(principal: float, rate: float, amort_months: int,
                      frequency: str='monthly',rate_type: str='fixed') -> float:
    if principal < 0 or amort_months <= 0 or frequency not in PER_YEAR:
        raise ValueError('Invalid loan inputs')
    payments_year = PER_YEAR[frequency]
    n = amort_months / 12 * payments_year
    r = periodic_rate(rate,payments_year,rate_type)
    if r == 0:
        base = principal / n
    else:
        base = principal * r / (-__import__('math').expm1(-n * __import__('math').log1p(r)))
    if frequency == 'accelerated-biweekly':
        return scheduled_payment(principal,rate,amort_months,'monthly',rate_type) / 2
    if frequency == 'accelerated-weekly':
        return scheduled_payment(principal,rate,amort_months,'monthly',rate_type) / 4
    return base


@dataclass
class PaymentLine:
    payment_number: int
    month: float
    rate: float
    payment: float
    interest: float
    principal: float
    balance: float
    extra: float
    negative_amortization: bool


def simulate(balance: float, rate: float, amort_months: int, horizon_months: int,
             frequency: str='monthly', rate_type: str='fixed',
             monthly_extra: float=0, annual_prepayment: float=0,
             variable_path_bps: list[int] | None=None,
             fixed_payment_variable: bool=False) -> dict:
    if not 0 <= rate <= 30 or not 0 < balance <= 100000000:
        raise ValueError('Bad rate or balance')
    if not 1 <= amort_months <= 480 or not 1 <= horizon_months <= 120:
        raise ValueError('Invalid amortization or horizon')
    if frequency not in PER_YEAR or monthly_extra < 0 or annual_prepayment < 0:
        raise ValueError('Invalid frequency or prepayment')
    f = PER_YEAR[frequency]
    num_periods = __import__('math').ceil(horizon_months * f / 12)
    due = scheduled_payment(balance,rate,amort_months,frequency,rate_type)
    original_due = due
    total_interest = total_paid = total_principal = total_extra = 0.0
    lines: list[PaymentLine] = []
    original_balance = balance
    variable_path_bps = variable_path_bps or []
    prev_rate = rate
    trigger = False
    for i in range(num_periods):
        if balance < 0.005:
            break
        elapsed = i / f * 12
        month_number = int(elapsed)
        shift = variable_path_bps[min(month_number,len(variable_path_bps)-1)] if variable_path_bps else 0
        current = min(30,max(0,rate + shift / 100)) if rate_type == 'variable' else rate
        if rate_type == 'variable' and not fixed_payment_variable and current != prev_rate:
            remaining_months = max(1,amort_months - month_number)
            due = scheduled_payment(balance,current,remaining_months,frequency,rate_type)
        prev_rate = current
        interest = balance * periodic_rate(current,f,rate_type)
        actual = min(balance + interest,due)
        extra = min(max(0,balance+interest-actual), monthly_extra * 12/f)
        if annual_prepayment and (i+1) % f == 0:
            extra += min(max(0,balance+interest-actual-extra),annual_prepayment)
        principal = actual + extra - interest
        negative = principal < -0.005
        if negative: trigger = True
        balance = max(0,balance-principal)
        total_interest += interest
        total_paid += actual + extra
        total_principal += principal
        total_extra += extra
        lines.append(PaymentLine(i+1,round((i+1)*12/f,3),round(current,5),
             round(actual+extra,2),round(interest,2),round(principal,2),
             round(balance,2),round(extra,2),negative))
    # Full-precision aggregates, rounding only at report boundary
    return {'regular_payment':round(original_due,2), 'periods_per_year':f,
            'frequency':frequency,'periods_elapsed':len(lines),
            'total_paid':round(total_paid,2),'total_interest':round(total_interest,2),
            'total_principal':round(total_principal,2),'total_extra':round(total_extra,2),
            'ending_balance':round(balance,2),'starting_balance':round(original_balance,2),
            'negative_amortization':trigger,
            'last_payment':lines[-1].payment if lines else 0,
            'schedule':[asdict(x) for x in lines]}


def compare_offers(mortgage, offers, horizon_months: int =36, discount_rate: float=4):
    """Net cost = payments + ending liability + out-of-pocket fees - starting debt.

    This treats different amortizations fairly over a common horizon. The
    interest-difference equals net cost difference when starting debt matches.
    Monthly payment savings and interest savings must never be added together.
    """
    from .schemas import Offer
    baseline = Offer(name='Your renewal offer',rate=mortgage.offered_rate,rate_type=mortgage.rate_type,
                     term_months=mortgage.term_months,type='personalized')
    all_offers = [baseline] + offers
    simulations = []
    for o in all_offers:
        term = min(o.term_months,horizon_months)
        # Caution: no assumption about rates beyond a quoted term.
        if o.term_months < horizon_months:
            horizon = o.term_months
        else: horizon = horizon_months
        loan = simulate(mortgage.balance,o.rate,o.amortization_months or mortgage.amortization_months,
               horizon,mortgage.frequency,o.rate_type,o.monthly_extra,o.annual_prepayment,
               o.variable_path_bps,o.fixed_payment_variable)
        fees_net = o.fees - o.fee_credit
        cost = loan['total_paid'] + loan['ending_balance'] - mortgage.balance + fees_net
        rows = loan['schedule']
        pv_payments = sum(p['payment']/((1+discount_rate/1200)**(p['month'])) for p in rows)
        pv_terminal = loan['ending_balance']/((1+discount_rate/1200)**horizon)
        pv_cost = pv_payments + pv_terminal + fees_net - mortgage.balance
        simulations.append({'offer':o.model_dump(), 'horizon_months':horizon,
           'loan':{k:v for k,v in loan.items() if k != 'schedule'},
           'schedule': rows, 'net_cost':round(cost,2), 'present_cost':round(pv_cost,2),
           'fees_net':round(fees_net,2),
           'not_comparable_full_horizon':o.term_months < horizon_months})
    ref=simulations[0]
    for scenario in simulations:
        scenario['vs_renewal']={
            'payment_per_period':round(ref['loan']['regular_payment']-scenario['loan']['regular_payment'],2),
            'interest':round(ref['loan']['total_interest']-scenario['loan']['total_interest'],2),
            'ending_balance':round(ref['loan']['ending_balance']-scenario['loan']['ending_balance'],2),
            'net_benefit':round(ref['net_cost']-scenario['net_cost'],2),
            'present_benefit':round(ref['present_cost']-scenario['present_cost'],2)}
    valid = [s for s in simulations if not s['not_comparable_full_horizon']]
    best = min(valid,key=lambda s:s['net_cost']) if valid else ref
    return {'scenarios':simulations,'best_name':best['offer']['name'],
       'horizon_months':horizon_months,
       'calculation_note':'Canadian nominal semiannual compounding for fixed rates; nominal monthly for variable. Contract conventions may differ. Total-interest and payment cash-flow savings are not additive. Shorter-than-horizon terms are not ranked as full-horizon alternatives.',
       'verified_market_offer':False}


def stress_paths(mortgage, comparison_rate=None,horizon_months=36):
    r = mortgage.offered_rate if comparison_rate is None else comparison_rate
    paths = {'falling -100 bps':[-100]*horizon_months,'unchanged':[0]*horizon_months,
       'rising +100 bps':[100]*horizon_months,'rising +200 bps':[200]*horizon_months,
       'up then down': [100 if m <12 else 200 if m <24 else 0 for m in range(horizon_months)]}
    output={}
    for name,p in paths.items():
        s=simulate(mortgage.balance,r,mortgage.amortization_months,horizon_months,
            mortgage.frequency,'variable',variable_path_bps=p)
        output[name]={k:v for k,v in s.items() if k != 'schedule'}
        output[name]['month_balances']=[item['balance'] for item in s['schedule']]
    return {'paths':output,'assumption':'Immediate basis-point rate changes held by path; adjustable payment is recalculated at rate changes. This is a scenario, not a rate forecast.'}
