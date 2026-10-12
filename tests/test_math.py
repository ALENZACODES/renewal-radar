import math,pytest
from renewal.domain.schemas import Mortgage,Offer
from renewal.domain.mortgage_math import periodic_rate,scheduled_payment,simulate,compare_offers,stress_paths

@pytest.mark.parametrize('freq', ['monthly','semi-monthly','biweekly','weekly','accelerated-biweekly','accelerated-weekly'])
def test_payment_frequency(freq):
    assert scheduled_payment(480000,5.49,228,freq)>0

@pytest.mark.parametrize('rate', [0,1,3,4.49,5.49,9,18])
def test_amortization_full(rate):
    m=simulate(250000,rate,240,120,'monthly')
    assert m['ending_balance']>=0
    assert abs(m['total_paid']+m['ending_balance']-250000-m['total_interest'])<=0.04


def test_nominal_canadian_fixed_conversion():
    assert periodic_rate(6,12,'fixed')==pytest.approx((1+0.06/2)**(1/6)-1)


def test_realistic_fixture_numbers():
    m=Mortgage()
    r=compare_offers(m,[Offer(name='Alternative',rate=4.49,term_months=36)],36)
    base,other=r['scenarios']
    assert base['loan']['regular_payment']==3378.66
    assert other['loan']['regular_payment']==3122.52
    assert base['loan']['total_interest']==74542.72
    assert other['loan']['total_interest']==60786.65
    assert other['vs_renewal']['interest']==13756.07
    assert other['vs_renewal']['ending_balance']==4535.04
    assert other['vs_renewal']['net_benefit']==13756.07


def test_fees_reduce_benefit():
    m=Mortgage()
    z=compare_offers(m,[Offer(name='A',rate=4.49,term_months=36,fees=1000,fee_credit=200)],36)
    assert z['scenarios'][1]['vs_renewal']['net_benefit']==12956.07


def test_longer_amortization_must_not_fake_interest_saving():
    m=Mortgage()
    z=compare_offers(m,[Offer(name='B',rate=5.49,term_months=36,amortization_months=300)],36)
    assert z['scenarios'][1]['loan']['regular_payment']<z['scenarios'][0]['loan']['regular_payment']
    assert z['scenarios'][1]['net_cost']>z['scenarios'][0]['net_cost']


def test_short_term_not_marked_comparable():
    z=compare_offers(Mortgage(),[Offer(name='1 year',rate=3,term_months=12)],36)
    assert z['scenarios'][1]['not_comparable_full_horizon'] is True
    assert z['best_name']=='Your renewal offer'


def test_no_negative_balance_when_overpay():
    z=simulate(1000,1,120,120,monthly_extra=9000)
    assert z['ending_balance']==0
    assert z['periods_elapsed']==1


def test_variable_can_trigger_negative_amortization():
    z=simulate(480000,1,228,36,rate_type='variable',fixed_payment_variable=True,
               variable_path_bps=[0]+[1900]*35)
    assert z['negative_amortization'] is True


def test_stress_paths():
    z=stress_paths(Mortgage(),horizon_months=36)
    assert len(z['paths'])==5
    assert z['paths']['rising +200 bps']['total_interest']>z['paths']['unchanged']['total_interest']


@pytest.mark.parametrize('rate', [-1,31])
def test_reject_invalid_rates(rate):
    with pytest.raises(ValueError):periodic_rate(rate)
