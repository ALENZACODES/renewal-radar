import pytest
from renewal.providers.bank_rates import parse_official_posted_html
from renewal.providers.tavily import official_url
from renewal.services.market import bank_catalog

HTML='''<table><thead><tr><th>Mortgage rate (posted)</th><th>Fixed rate</th></tr></thead><tbody><tr><td>5-year fixed</td><td>5.99%</td></tr><tr><td>3-year fixed</td><td>5.29%</td></tr></tbody></table>'''

def test_labelled_posted_table():
    x=parse_official_posted_html(HTML)
    assert x['value']==5.99


def test_ambiguous_table_not_promoted():
    x=parse_official_posted_html(HTML+HTML.replace('5.99%','6.19%'))
    assert x['value'] is None


def test_promotional_rate_not_posted():
    x=parse_official_posted_html('<table><tr><td>5-year fixed</td><td>4.00%</td></tr></table>')
    assert x['value'] is None

@pytest.mark.parametrize('url,expected',[
    ('https://www.rbcroyalbank.com/mortgages/mortgage-rates.html',True),
    ('https://notrbcroyalbank.com/test',False),
    ('http://td.com/mortgage',False),
    ('https://td.com.evil.org/',False),
    ('https://www.nbc.ca/test',True)])
def test_official_url_allowlist(url,expected):
    assert official_url(url) is expected


def test_all_six_banks_have_sources():
    rows=bank_catalog();assert len(rows)==6
    assert all(x['source_url'].startswith('https://') and not x['verified'] for x in rows)
