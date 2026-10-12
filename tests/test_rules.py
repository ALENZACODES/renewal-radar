import pytest
from renewal.domain.schemas import Mortgage
from renewal.domain.rules import mqr,switch_decision,penalty_estimate

def test_mqr_floor_and_buffer():
    assert mqr(2)==5.25
    assert mqr(5.49)==7.49


def test_uninsured_straight_switch():
    x=switch_decision(Mortgage())
    assert x['status']=='potentially-exempt'
    assert x['prescribed_mqr_applies']=='not-prescribed'
    assert x['qualifying_rate'] is None
    assert x['sources']

@pytest.mark.parametrize('modification',[{'cash_out':10000},{'amortization_increase':True},{'fees_financed':3100}])
def test_refinance_exclusions(modification):
    x=switch_decision(Mortgage(**modification))
    assert x['status']=='new-underwriting'
    assert x['qualifying_rate']==7.49

@pytest.mark.parametrize('modification',[{'standalone':False},{'combined_loan_plan':True},{'existing_lender_federally_regulated':False},{'new_lender_federally_regulated':None},{'insurance_status':'unknown'}])
def test_needs_review(modification):
    x=switch_decision(Mortgage(**modification))
    assert x['status']=='review'


def test_insured_pathway_and_underwriting_warning():
    x=switch_decision(Mortgage(insurance_status='insured'))
    assert x['status']=='potentially-exempt'
    assert 'approval' in x['disclaimer'].lower()


def test_no_early_penalty_at_maturity():
    x=penalty_estimate(500000,5,'fixed',0)
    assert x['estimated_penalty']==0


def test_variable_proxy():
    x=penalty_estimate(400000,6,'variable',24,4,contract_method='simple')
    assert x['three_month_interest']==6000
    assert x['estimated_penalty']==6000


def test_fixed_higher_of_penalty():
    x=penalty_estimate(200000,6,'fixed',36,4,contract_method='simple')
    assert x['three_month_interest']==3000
    assert x['ird_estimate']==12000
    assert x['estimated_penalty']==12000


def test_undocumented_ird_stays_unknown():
    x=penalty_estimate(200000,6,'fixed',36,contract_method='unknown')
    assert x['ird_estimate'] is None and x['estimated_penalty'] is None


def test_discount_changes_ird():
    x=penalty_estimate(200000,4,'fixed',24,comparison_rate=3,original_posted_rate=6,
                       original_discount=2,contract_method='posted-discount')
    assert x['ird_estimate']==20000
