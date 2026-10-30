from datetime import date
from decimal import Decimal as D

import pytest

from renewal.rates.models import CHARTERED, Observation, Quality, term_code_to_months
from renewal.rates.sources import dedupe, parse_lender_csv, parse_statcan_csv, parse_valet_csv

VALET = '''"TERMS AND CONDITIONS"
"https://www.bankofcanada.ca/terms/"

"SERIES"
"id","label","description"
"V80691335","Conventional mortgage, 5-year","..."

"OBSERVATIONS"
"date","V80691335"
"2026-09-30","6.09"
"2026-10-07",""
"2026-10-14","6.19"
'''

STATCAN = '''\ufeff"REF_DATE","GEO","DGUID","UOM","UOM_ID","SCALAR_FACTOR","SCALAR_ID","VECTOR","COORDINATE","VALUE","STATUS","SYMBOL","TERMINATED","DECIMALS"
"2026-07","Canada","x","Percent","239","units","0","v733833","1","6.09","","","","2"
"2026-08","Canada","x","Percent","239","units","0","v733833","1","","..","","","2"
'''

LENDER = '''date,lender,term,rate_pct,snapshot_url,boc_5y_posted_ref,quality
2015-05-06,RBC,5y_fixed,4.64,https://web.archive.org/web/2015/x,4.64,posted_ok
2015-05-06,rbc,prime,2.85,https://web.archive.org/web/2015/x,4.64,posted_ok
2015-05-06,rbc,variable_5y,2.6,https://web.archive.org/web/2015/x,4.64,likely_special_offer
2015-05-06,rbc,1y_fixed,,https://web.archive.org/web/2015/x,4.64,posted_ok
'''


def test_valet_skips_metadata_and_blank_values():
    rows = list(parse_valet_csv(VALET, 'V80691335'))
    assert [r.observed for r in rows] == [date(2026, 9, 30), date(2026, 10, 14)]
    assert rows[0].lender == CHARTERED and rows[0].term_months == 60
    assert rows[0].quality is Quality.OFFICIAL
    assert rows[0].source_url.endswith('V80691335/csv')


def test_valet_wrong_series_and_missing_header():
    with pytest.raises(ValueError):
        list(parse_valet_csv(VALET, 'V80691333'))
    with pytest.raises(ValueError):
        list(parse_valet_csv('"SERIES"\n'))


def test_statcan_monthly():
    rows = list(parse_statcan_csv(STATCAN))
    assert len(rows) == 1
    assert rows[0].observed == date(2026, 7, 1) and rows[0].rate == D('6.09')
    assert 'v733833' in rows[0].source_id


def test_lender_csv_terms_quality_and_case():
    rows = list(parse_lender_csv(LENDER))
    assert len(rows) == 3
    five, prime, var = rows
    assert five.lender == 'rbc' and five.term_months == 60 and five.quality is Quality.POSTED_OK
    assert prime.rate_type == 'prime' and prime.term_months is None
    assert var.rate_type == 'variable' and var.quality is Quality.LIKELY_SPECIAL
    assert five.source_id == 'wayback'


def test_lender_csv_without_quality_is_unverified():
    rows = list(parse_lender_csv('date,lender,term,rate_pct\n2026-10-11,td,5y_fixed,5.34\n', 'scraper'))
    assert rows[0].quality is Quality.UNVERIFIED and rows[0].source_id == 'scraper'


def test_term_codes():
    assert term_code_to_months('10y_fixed') == (120, 'fixed')
    assert term_code_to_months('variable_5y') == (60, 'variable')
    with pytest.raises(ValueError):
        term_code_to_months('6y_fixed')


@pytest.mark.parametrize('kw', [
    {'rate': D('31')}, {'lender': ''}, {'rate_type': 'arm'}, {'term_months': 0},
    {'rate_type': 'prime', 'term_months': 12}])
def test_observation_validation(kw):
    base = dict(observed=date(2026, 1, 1), lender='td', term_months=60, rate_type='fixed',
                rate=D('5'), source_id='s', source_url='', quality=Quality.UNVERIFIED)
    base.update(kw)
    with pytest.raises(ValueError):
        Observation(**base)


def test_dedupe_prefers_better_quality():
    a = Observation(date(2026, 1, 1), 'td', 60, 'fixed', D('5'), 's', '', Quality.LIKELY_SPECIAL)
    b = Observation(date(2026, 1, 1), 'td', 60, 'fixed', D('6'), 's', '', Quality.POSTED_OK)
    c = Observation(date(2026, 1, 1), 'td', None, 'prime', D('4'), 's', '', Quality.POSTED_OK)
    assert set(dedupe([a, b, c])) == {b, c}
