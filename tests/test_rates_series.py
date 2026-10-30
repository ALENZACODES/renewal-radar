from datetime import date
from decimal import Decimal as D
from pathlib import Path

from fastapi.testclient import TestClient

from renewal.rates.models import CHARTERED, Observation, Quality
from renewal.rates.pipeline import build, main, write
from renewal.rates.series import RateBook
from renewal.rates.service import REFERENCE_DIR, workbench_rates
from renewal.rates.validate import Reference, boc_five_year, classify, quality_report


def obs(day, lender, term, rate, quality=Quality.POSTED_OK, sid='s', url='u', kind='fixed'):
    return Observation(day, lender, term, kind, D(rate), sid, url, quality)


BOC = [obs(date(2026, 1, 7), CHARTERED, 60, '6.00', Quality.OFFICIAL, 'V80691335'),
       obs(date(2026, 3, 4), CHARTERED, 60, '6.20', Quality.OFFICIAL, 'V80691335'),
       obs(date(2026, 3, 4), CHARTERED, 12, '6.40', Quality.OFFICIAL, 'V80691333')]


def test_reference_staleness():
    ref = Reference(BOC[:2])
    assert ref.at(date(2026, 1, 20)) == D('6.00')
    assert ref.at(date(2026, 3, 1)) is None   # 53 days after the January point
    assert ref.at(date(2025, 12, 1)) is None


def test_classify_whole_capture():
    cap = [obs(date(2026, 3, 10), 'td', 60, '6.49', Quality.UNVERIFIED, url='a'),
           obs(date(2026, 3, 10), 'td', 36, '6.05', Quality.UNVERIFIED, url='a'),
           obs(date(2026, 3, 11), 'td', 60, '4.79', Quality.UNVERIFIED, url='b'),
           obs(date(2026, 3, 12), 'td', 36, '5.00', Quality.UNVERIFIED, url='c')]
    out = classify(BOC + cap, boc_five_year(BOC))
    q = {(o.observed.day, o.term_months): o.quality for o in out if o.lender == 'td'}
    assert q[(10, 60)] is q[(10, 36)] is Quality.POSTED_OK
    assert q[(11, 60)] is Quality.LIKELY_SPECIAL
    assert q[(12, 36)] is Quality.UNVERIFIED
    report = quality_report(out)
    assert report['td']['rows'] == 4 and report['td']['posted_ok'] == 2


def test_ratebook_lookup_and_proxy():
    book = RateBook(BOC + [obs(date(2026, 2, 1), 'td', 60, '6.49'),
                           obs(date(2026, 2, 1), 'td', 36, '4.00', Quality.LIKELY_SPECIAL)])
    hit = book.posted_at('TD', 60, date(2026, 2, 15))
    assert hit.rate == D('6.49') and not hit.proxy and hit.age_days == 14
    proxy = book.posted_at('td', 12, date(2026, 3, 5))
    assert proxy.proxy and proxy.lender == CHARTERED
    assert book.posted_at('td', 12, date(2026, 3, 5), allow_proxy=False) is None
    assert book.posted_at('td', 36, date(2026, 2, 2), allow_proxy=False) is None  # special excluded
    table = book.table_at('td', date(2026, 3, 5))
    assert set(table) == {12, 60}
    assert table[60].rate == D('6.49') and not table[60].proxy  # lender row beats newer proxy
    assert table[12].proxy
    assert book.terms('td') == [60]
    assert [o.rate for o in book.series(CHARTERED, 60, start=date(2026, 2, 1))] == [D('6.20')]


def test_max_age_days():
    book = RateBook([obs(date(2020, 1, 1), 'rbc', 60, '5.34')])
    assert book.posted_at('rbc', 60, date(2020, 3, 1)) is not None
    assert book.posted_at('rbc', 60, date(2021, 1, 1)) is None


def test_reference_build_is_reproducible(tmp_path: Path):
    observations = build(REFERENCE_DIR)
    first = write(observations, tmp_path / 'a')
    second = write(build(REFERENCE_DIR), tmp_path / 'b')
    assert first == second
    assert len(observations) > 10_000
    assert main([str(REFERENCE_DIR), str(tmp_path / 'c')]) == 0


def test_reference_book_real_values():
    book = RateBook(build(REFERENCE_DIR))
    # RBC capture from May 2015 is a posted page within 0.6 pp of BoC.
    hit = book.posted_at('rbc', 60, date(2015, 6, 1))
    assert hit is not None and not hit.proxy and hit.quality is Quality.POSTED_OK
    boc = book.posted_at(CHARTERED, 60, date(2026, 10, 9))
    assert boc.rate == D('6.19')
    inputs = workbench_rates(book, 'td', date(2023, 3, 1), date(2026, 10, 12), 60)
    assert inputs['original_posted_rate'] is not None
    assert 60 in inputs['current_posted']
    assert inputs['uses_proxy'] is True


def test_rates_api():
    from renewal.main import app
    with TestClient(app) as c:
        r = c.get('/api/v5/rates/posted', params={'lender': 'rbc', 'term_months': 60, 'on': '2015-06-01'})
        assert r.status_code == 200 and r.json()['quality'] == 'posted_ok'
        assert c.get('/api/v5/rates/posted', params={'lender': 'rbc', 'term_months': 60,
                                                     'on': '1900-01-01'}).status_code == 404
        t = c.get('/api/v5/rates/table', params={'lender': 'td', 'on': '2026-10-12'}).json()
        assert '60' in t['table']
        w = c.get('/api/v5/rates/workbench-inputs', params={'lender': 'td', 'funded': '2023-03-01',
                                                            'payout': '2026-10-12'})
        assert w.status_code == 200 and w.json()['current_posted']['60']
        assert c.get('/api/v5/rates/workbench-inputs', params={'lender': 'td', 'funded': '2026-03-01',
                                                               'payout': '2023-10-12'}).status_code == 422
