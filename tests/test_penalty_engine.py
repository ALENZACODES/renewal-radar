from dataclasses import replace
from decimal import Decimal as D
import pytest
from renewal.penalty import calculate_penalty, forecast_penalty, optimize_privilege, PenaltyInputs
from renewal.penalty.models import Method
from renewal.penalty.profiles import profile_for, lender_profiles

BASE=PenaltyInputs(balance=D('400000'),annual_rate=D('5'),remaining_months=24,
                   lender='td',documented_discount=D('1'),comparison_posted_rate=D('4'))

def test_documented_td_discount_and_ird():
    r=calculate_penalty(BASE)
    assert r.three_month_interest==D('5000.00')
    assert r.interest_rate_differential==D('16000.00')
    assert r.total_estimate==D('16000.00')
    assert r.controlling_method=='ird'

def test_variable_uses_three_months_only():
    r=calculate_penalty(replace(BASE,rate_type='variable'))
    assert r.total_estimate==D('5000.00')
    assert r.interest_rate_differential is None

def test_unknown_lender_requires_evidence_not_spurious_exact_quote():
    r=calculate_penalty(replace(BASE,lender='does_not_exist'))
    assert r.total_estimate is None
    assert r.status=='floor_only'
    assert 'verified lender-specific methodology' in r.missing_fields

def test_missing_discount_blocks_fixed_calculation():
    r=calculate_penalty(replace(BASE,documented_discount=None))
    assert r.total_estimate is None
    assert r.three_month_interest==D('5000.00')

def test_missing_comparison_blocks_fixed_calculation():
    r=calculate_penalty(replace(BASE,comparison_posted_rate=None))
    assert r.status=='floor_only'
    assert r.total_estimate is None

def test_simple_contract_variant():
    r=calculate_penalty(replace(BASE,explicit_method=Method.SIMPLE))
    assert r.interest_rate_differential==D('8000.00')

def test_cibc_discount_adds_to_three_month_floor():
    r=calculate_penalty(replace(BASE,lender='cibc'))
    assert r.three_month_interest==D('6000.00')
    assert r.interest_rate_differential==D('16000.00')

def test_scotia_pv_requires_amortization_and_not_exact():
    r=calculate_penalty(replace(BASE,lender='scotia'))
    assert r.total_estimate is None
    assert 'remaining amortization for PV model' in r.missing_fields
    r2=calculate_penalty(replace(BASE,lender='scotia',remaining_amortization_months=240))
    assert r2.interest_rate_differential >= 0
    assert r2.status=='estimate'
    assert any('illustrative' in w.lower() for w in r2.warnings)

def test_zero_at_maturity_and_open():
    assert calculate_penalty(replace(BASE,remaining_months=0)).total_estimate==0
    assert calculate_penalty(replace(BASE,is_open=True)).total_estimate==0

def test_additional_fees_do_not_get_dropped():
    r=calculate_penalty(replace(BASE,cashback_clawback=D('900'),discharge_fee=D('350'),
                                administration_fee=D('120'),reinvestment_fee=D('50')))
    assert r.additional_fees==D('1420.00')
    assert r.total_estimate==D('17420.00')

def test_partial_payout_is_not_full_balance():
    r=calculate_penalty(replace(BASE,payout_amount=D('100000')))
    assert r.interest_rate_differential==D('4000.00')

def test_privilege_only_applies_if_contract_allows():
    barred=calculate_penalty(replace(BASE,privilege_available=D('100000')))
    allowed=calculate_penalty(replace(BASE,privilege_available=D('100000'),
                                     privilege_applicable_to_full_payout=True))
    assert barred.total_estimate==D('16000.00')
    assert allowed.total_estimate==D('12000.00')
    assert any('not assumed' in warning for warning in barred.warnings)

def test_optimization_reports_savings():
    s=optimize_privilege(BASE,D('100000'),True)
    assert s['modelled_penalty_reduction']=='4000.00'

def test_forecast_reaches_zero_at_maturity():
    r=forecast_penalty(BASE,24,[D('4')]*25)
    assert len(r)==25
    assert r[-1]['penalty']['total_estimate']=='0.00'

def test_rate_path_changes_penalty():
    r=forecast_penalty(BASE,2,[D('4'),D('5'),D('6')])
    assert D(r[0]['penalty']['interest_rate_differential'])>D(r[1]['penalty']['interest_rate_differential'])

def test_floor_90_day_variant():
    r=calculate_penalty(replace(BASE,rate_type='variable',three_month_basis='90_days'))
    assert r.three_month_interest==D('4931.51')

def test_serialization_contains_strings_not_floats():
    r=calculate_penalty(BASE).as_dict()
    assert isinstance(r['total_estimate'],str)
    assert r['audit']['rate_units']=='percentage_points'

@pytest.mark.parametrize('field,value',[
 ('balance',D('0')),('annual_rate',D('-1')),('remaining_months',-1),
 ('privilege_available',D('-10')),('payout_amount',D('600000')),
 ('comparison_posted_rate',D('31')),('documented_discount',D('-1')),
])
def test_rejects_invalid_inputs(field,value):
    with pytest.raises(ValueError):
        calculate_penalty(replace(BASE,**{field:value}))

@pytest.mark.parametrize('lender', ['rbc','rbc_pv','td','scotia','cibc','bmo','nbc','first_national','mcap'])
def test_profiles_have_source_links(lender):
    p=profile_for(lender)
    assert p.source_url.startswith('https://')
    assert p.version

def test_registry_is_unique_and_explicit():
    profiles=lender_profiles()
    assert len(set(p['code'] for p in profiles))==len(profiles)
    assert profile_for('bmo').source_verified is False

@pytest.mark.parametrize('balance', ['1000','10000','100000','2000000'])
@pytest.mark.parametrize('rate', ['0','1.5','4.99','9.5'])
def test_variable_penalty_scales_linearly(balance,rate):
    r=calculate_penalty(replace(BASE,balance=D(balance),annual_rate=D(rate),rate_type='variable'))
    assert r.three_month_interest== (D(balance)*D(rate)/D('400')).quantize(D('.01'))

@pytest.mark.parametrize('months', [1,12,24,60,120])
def test_fixed_penalty_not_below_three_month_floor(months):
    r=calculate_penalty(replace(BASE,remaining_months=months))
    assert r.core_charge>=r.three_month_interest

@pytest.mark.parametrize('comparison', ['1','2','3','4','5','6','7','8'])
def test_higher_comparison_rates_do_not_increase_ird(comparison):
    low=calculate_penalty(replace(BASE,comparison_posted_rate=D(comparison)))
    high=calculate_penalty(replace(BASE,comparison_posted_rate=D(comparison)+D('0.1')))
    assert low.interest_rate_differential>=high.interest_rate_differential
