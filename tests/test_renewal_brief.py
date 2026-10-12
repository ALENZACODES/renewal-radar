from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from renewal.cases.brief import ConfirmedFacts, build_brief
from renewal.rates.models import CHARTERED, Observation, Quality
from renewal.rates.series import RateBook

TODAY = date(2026, 10, 12)


def obs(day, lender, term, rate, q=Quality.POSTED_OK):
    return Observation(day, lender, term, 'fixed', D(rate), 'src', 'https://example.ca', q)


BOOK = RateBook([
    obs(date(2022, 2, 23), 'td', 60, '4.89'),
    obs(date(2026, 10, 7), CHARTERED, 12, '6.09', Quality.OFFICIAL),
    obs(date(2026, 10, 7), CHARTERED, 36, '6.05', Quality.OFFICIAL),
    obs(date(2026, 10, 7), CHARTERED, 60, '6.19', Quality.OFFICIAL),
])


def facts(**kw):
    base = dict(lender='td', balance=D('412345.67'), rate_pct=D('2.79'), maturity_date=date(2027, 3, 1),
                term_months=60, amortization_months=234, renewal_rate_pct=D('5.94'))
    base.update(kw)
    return ConfirmedFacts(**base)


def test_brief_offer_and_break_sections():
    b = build_brief(facts(), BOOK, TODAY)
    assert b.funded_on == date(2022, 3, 1) and b.days_to_maturity == 140
    assert b.offer['posted_rate_pct'] == '6.19' and b.offer['posted_is_proxy'] is True
    assert b.offer['discount_from_posted_pp'] == '0.25'
    assert D(b.offer['payment_at_offer']) < D(b.offer['payment_at_posted'])
    assert any('less than 0.50 points' in c for c in b.cautions)
    br = b.break_today
    assert br['remaining_months'] == 5 and br['discount_pp'] == '2.10'
    # contract 2.79 is far below today's market, so three months' interest controls
    assert br['controlling_method'] == '3_months'
    assert br['total_estimate'] == br['three_month_interest']
    uses = {s['use'] for s in b.sources}
    assert {'posted rate today', 'posted rate at funding', 'posted 60-month rate today'} <= uses
    assert b.as_dict()['notice'].startswith('Estimates only')


def test_missing_inputs_are_listed_not_guessed():
    b = build_brief(facts(renewal_rate_pct=None, lender='bmo'), BOOK, TODAY)
    assert b.offer is None
    assert any('renewal offer rate' in m for m in b.missing)
    assert any('posted 60-month rate at funding' in m for m in b.missing)
    assert b.break_today['status'] in ('floor_only', 'estimate')


def test_contract_discount_removes_funding_gap():
    b = build_brief(facts(lender='bmo', contract_discount=D('1.5')), BOOK, TODAY)
    assert not any('at funding' in m for m in b.missing)
    assert b.break_today['discount_pp'] == '1.5'


def test_matured_term_has_no_break_section():
    b = build_brief(facts(maturity_date=date(2026, 10, 1)), BOOK, TODAY)
    assert b.break_today is None
    assert any('matured' in c for c in b.cautions)


def test_window_caution_and_validation():
    b = build_brief(facts(maturity_date=date(2026, 12, 1)), BOOK, TODAY)
    assert any('120 days' in c for c in b.cautions)
    with pytest.raises(ValueError):
        build_brief(facts(maturity_date=date(2032, 1, 1)), BOOK, TODAY)
    for kw in ({'balance': D('0')}, {'term_months': 3}, {'amortization_months': 12},
               {'renewal_rate_pct': D('40')}):
        with pytest.raises(ValueError):
            facts(**kw)


def test_brief_api():
    from renewal.main import app
    body = {'lender': 'td', 'balance': '412345.67', 'rate_pct': '2.79', 'maturity_date': '2027-03-01',
            'term_months': 60, 'amortization_months': 234, 'renewal_rate_pct': '5.94'}
    with TestClient(app) as c:
        r = c.post('/api/v5/cases/brief', params={'as_of': '2026-10-12'}, json=body)
        assert r.status_code == 200, r.text
        assert r.json()['offer']['posted_rate_pct'] == '6.19'
        bad = c.post('/api/v5/cases/brief', json={**body, 'rate_type': 'arm'})
        assert bad.status_code == 422
