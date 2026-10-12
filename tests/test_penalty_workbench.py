from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from renewal.penalty.comparison import TermRule
from renewal.penalty.methods import DiscountSource, all_specs, spec_for
from renewal.penalty.workbench import WorkbenchCase, run_workbench

TABLE = {12: D('6.00'), 24: D('5.90'), 36: D('6.05'), 60: D('6.49')}


def case(**kw):
    base = dict(lender='td', balance=D('400000'), contract_rate=D('5.79'),
                term_start=date(2023, 3, 1), maturity=date(2028, 3, 1),
                payout=date(2026, 10, 15), current_posted=TABLE,
                original_posted_rate=D('6.49'))
    base.update(kw)
    return WorkbenchCase(**base)


def test_posted_minus_discount_from_original_posted():
    r = run_workbench(case())
    assert r.remaining_months == 17
    assert r.discount_pp == D('0.70') and r.discount_basis == 'original_posted_minus_contract'
    assert r.comparison['terms_used'] == [12]
    # IRD = 400000 x (5.79 - (6.00 - 0.70)) x 17/12 / 100 = 2776.67, below 3-month 5790
    assert r.estimate['interest_rate_differential'] == '2776.67'
    assert r.estimate['controlling_method'] == '3_months'
    assert r.estimate['total_estimate'] == '5790.00'


def test_ird_controls_when_rates_fall():
    low = {k: v - D('2.5') for k, v in TABLE.items()}
    r = run_workbench(case(current_posted=low))
    assert r.estimate['controlling_method'] == 'ird'
    assert D(r.estimate['total_estimate']) > D('5790')


def test_contract_discount_takes_precedence():
    r = run_workbench(case(contract_discount=D('1.10')))
    assert r.discount_pp == D('1.10') and r.discount_basis == 'contract'


def test_missing_discount_is_reported_not_guessed():
    r = run_workbench(case(original_posted_rate=None))
    assert r.discount_basis == 'missing'
    assert r.estimate['status'] == 'floor_only'
    assert 'documented original rate discount' in r.estimate['missing_fields']


def test_negative_derived_discount_is_clamped_with_warning():
    r = run_workbench(case(original_posted_rate=D('5.00')))
    assert r.discount_pp == 0
    assert any('above the posted rate' in w for w in r.warnings)


def test_sensitivity_covers_rules_and_flags_large_spread():
    steep = {12: D('3.00'), 24: D('5.00'), 36: D('6.05'), 60: D('6.49')}
    r = run_workbench(case(current_posted=steep, contract_rate=D('6.20'), original_posted_rate=D('6.49')))
    rules = {s['rule'] for s in r.sensitivity}
    assert {'nearest', 'round_down', 'round_up', 'interpolate'} <= rules
    assert any('comparison-term rule alone' in w for w in r.warnings)


def test_override_rule_is_used():
    r = run_workbench(case(term_rule_override=TermRule.ROUND_UP))
    assert r.comparison['terms_used'] == [24]


def test_cashback_clawback_added_as_fee():
    r = run_workbench(case(cashback=D('6000')))
    assert r.clawback == D('1700.00')
    assert r.estimate['additional_fees'] == '1700.00'


def test_open_mortgage_has_no_charge():
    r = run_workbench(case(is_open=True))
    assert r.estimate['status'] == 'no_charge_modelled'


def test_payout_before_start_rejected():
    with pytest.raises(ValueError):
        run_workbench(case(payout=date(2022, 1, 1)))


def test_specs():
    assert spec_for('unknown-bank').lender == 'generic'
    assert spec_for('bmo').verified is False
    assert spec_for('cibc').discount_source is DiscountSource.CONTRACT
    assert {s['lender'] for s in all_specs()} >= {'rbc', 'td', 'scotia', 'cibc'}


def test_workbench_api():
    from renewal.main import app
    body = {'lender': 'td', 'balance': '400000', 'contract_rate': '5.79',
            'term_start': '2023-03-01', 'maturity': '2028-03-01', 'payout': '2026-10-15',
            'current_posted': {'12': '6.00', '24': '5.90', '36': '6.05', '60': '6.49'},
            'original_posted_rate': '6.49'}
    with TestClient(app) as c:
        r = c.post('/api/penalty/v3/workbench', json=body)
        assert r.status_code == 200, r.text
        assert r.json()['estimate']['total_estimate'] == '5790.00'
        bad = c.post('/api/penalty/v3/workbench', json={**body, 'payout': '2020-01-01'})
        assert bad.status_code == 422
        assert c.get('/api/penalty/v3/methods').json()['methods']
