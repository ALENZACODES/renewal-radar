from pathlib import Path

import pytest

from renewal.scraper.lenders import SOURCES, source
from renewal.scraper.parse import parse_page, parse_rows, parse_text, _clean_soup

F = Path(__file__).parent / 'fixtures' / 'scraper'
RBC_PRIME = source('rbc').prime_label


def rates(html, label=r'\bprime rate\b'):
    return {k: v.rate for k, v in parse_page(html, label).items()}


def test_rbc_table_fixture():
    r = rates((F / 'rbc.html').read_text(), RBC_PRIME)
    assert r == {'1y_fixed': 6.09, '2y_fixed': 5.89, '3y_fixed': 6.05, '4y_fixed': 5.99,
                 '5y_fixed': 6.09, '7y_fixed': 6.40, '10y_fixed': 6.75,
                 'variable_5y': 4.55, 'prime': 4.45}


def test_script_values_ignored():
    assert 9.99 not in rates((F / 'rbc.html').read_text()).values()


def test_td_cards_word_order_and_nbsp():
    r = rates((F / 'td.html').read_text(), source('td').prime_label)
    assert r['5y_fixed'] == 6.09 and r['3y_fixed'] == 6.05
    assert r['variable_5y'] == 4.35 and r['prime'] == 4.60


def test_real_archive_capture_matches_reference_dataset():
    r = rates((F / 'rbc_archive_2015-05-06.html').read_text(errors='replace'), RBC_PRIME)
    assert r == {'1y_fixed': 3.14, '2y_fixed': 3.04, '3y_fixed': 3.65, '4y_fixed': 4.39,
                 '5y_fixed': 4.64, '7y_fixed': 5.30, '10y_fixed': 6.10, 'prime': 2.85}


def test_posted_column_preferred_over_special():
    html = ('<table><tr><th>Term</th><th>Special offer</th><th>Posted rate</th></tr>'
            '<tr><td>5 Year Fixed</td><td>4.09%</td><td>6.09%</td></tr></table>')
    assert rates(html)['5y_fixed'] == 6.09


def test_first_rate_used_without_posted_header():
    html = ('<h2>Fixed Mortgage Rates</h2><table><tr><td>Closed 1 Year</td><td>3.500%</td>'
            '<td>3.200%</td></tr><tr><td>5 Year</td><td>5.290%</td><td>4.090%</td></tr></table>')
    r = rates(html)
    assert r['1y_fixed'] == 3.5 and r['5y_fixed'] == 5.29


def test_special_rows_skipped():
    html = ('<table><tr><td>5 Year Fixed Special Offer</td><td>3.99%</td></tr>'
            '<tr><td>5 Year Fixed</td><td>6.09%</td></tr></table>')
    assert rates(html)['5y_fixed'] == 6.09


def test_10_year_not_read_as_1_year():
    r = rates('<p>10 Year Fixed 6.75%</p><p>1 Year Fixed 6.09%</p>')
    assert r['10y_fixed'] == 6.75 and r['1y_fixed'] == 6.09


@pytest.mark.parametrize('html', ['<p>5 year fixed save 50%</p>', '<p>prime rate change of 1.00%</p>',
                                  '<p>6 year fixed 5.00%</p>'])
def test_rejects_implausible(html):
    assert rates(html) == {}


def test_variable_spread_not_taken_as_rate():
    html = '<table><tr><td>5 Year Variable</td><td>Prime - 0.90%</td><td>3.55%</td></tr></table>'
    assert rates(html)['variable_5y'] == 3.55


def test_evidence_and_method_reported():
    parsed = parse_page((F / 'rbc.html').read_text())
    assert parsed['5y_fixed'].method == 'row'
    assert '5 Year Fixed' in parsed['5y_fixed'].evidence
    text_only = parse_text('Our five-year fixed rate is 5.99% today')
    assert text_only['5y_fixed'].method == 'text'


def test_rows_win_over_text():
    soup = _clean_soup('<p>5 year fixed rate 4.99%</p><table><tr><td>5 Year Fixed</td><td>6.09%</td></tr></table>')
    assert parse_rows(soup)['5y_fixed'].rate == 6.09


def test_registry():
    assert {'rbc', 'td', 'bmo', 'scotia', 'cibc', 'national'} <= {s.code for s in SOURCES}
    assert all(s.url.startswith('https://') for s in SOURCES)
    with pytest.raises(KeyError):
        source('nope')
