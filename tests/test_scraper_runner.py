import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from renewal.rates.models import CHARTERED, Observation, Quality
from renewal.rates.validate import Reference
from renewal.scraper.fetch import user_agent
from renewal.scraper.lenders import LenderSource
from renewal.scraper.robots import RobotsPolicy
from renewal.scraper.runner import already_ran, assess, previous_rates, run, save

F = Path(__file__).parent / 'fixtures' / 'scraper'
RBC = LenderSource('rbc', 'RBC', 'https://www.rbc.example/rates', r'\bRBC Royal Bank prime rate\b')
TD = LenderSource('td', 'TD', 'https://www.td.example/rates')
BAD = LenderSource('bad', 'Broken', 'https://broken.example/rates')
DAY = date(2026, 10, 12)


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def robots(rules=None, crawl_delay=None):
    def fetch(url):
        if 'broken' in url:
            raise OSError('down')
        body = 'User-agent: *\n' + (rules or 'Allow: /\n')
        if crawl_delay:
            body += f'Crawl-delay: {crawl_delay}\n'
        return body
    return RobotsPolicy(user_agent(), fetch)


def ref(rate='6.09'):
    return Reference([Observation(date(2026, 10, 7), CHARTERED, 60, 'fixed', D(rate), 'V80691335', '',
                                  Quality.OFFICIAL)])


def test_robots_allow_disallow_and_fail_closed():
    policy = robots('Disallow: /private/\n')
    assert policy.allowed('https://x.ca/rates')
    assert not policy.allowed('https://x.ca/private/rates')
    assert not policy.allowed('https://broken.example/rates')
    assert not policy.allowed('http://x.ca/rates')   # plain http never crawled


def test_robots_cached_per_host():
    calls = []
    policy = RobotsPolicy('ua', lambda u: calls.append(u) or 'User-agent: *\nAllow: /\n')
    policy.allowed('https://x.ca/a')
    policy.allowed('https://x.ca/b')
    assert calls == ['https://x.ca/robots.txt']


def test_run_spacing_skips_and_errors():
    pages = Pages({RBC.url: (F / 'rbc.html').read_text(), TD.url: RuntimeError('timeout')})
    sleeps = []
    out = run([RBC, BAD, TD], pages, robots(), DAY, sleep=sleeps.append)
    assert out['rbc'].status == 'ok' and out['rbc'].rates['5y_fixed'] == 6.09
    assert out['bad'].status == 'skipped_robots'
    assert out['td'].status == 'error' and 'timeout' in out['td'].error
    assert sleeps == [10.0]
    assert pages.calls == [RBC.url, TD.url]


def test_crawl_delay_respected():
    pages = Pages({RBC.url: '<p>x</p>', TD.url: '<p>y</p>'})
    sleeps = []
    out = run([RBC, TD], pages, robots(crawl_delay=30), DAY, sleep=sleeps.append)
    assert sleeps == [30.0]
    assert out['td'].status == 'no_rates_parsed'


def test_once_per_day(tmp_path):
    pages = Pages({RBC.url: (F / 'rbc.html').read_text()})
    first = run([RBC], pages, robots(), DAY, sleep=lambda s: None)
    save(first, DAY, tmp_path)
    assert already_ran(tmp_path, DAY) == {'rbc'}
    again = run([RBC], pages, robots(), DAY, skip=already_ran(tmp_path, DAY))
    assert again['rbc'].status == 'skipped_today' and len(pages.calls) == 1
    save(again, DAY, tmp_path)
    assert json.loads((tmp_path / '2026-10-12.json').read_text())['rbc']['status'] == 'ok'


def test_assess_quality_and_jump_alerts(tmp_path):
    pages = Pages({RBC.url: (F / 'rbc.html').read_text()})
    res = run([RBC], pages, robots(), DAY)
    assess(res, DAY, ref('6.19'), {'rbc': {'5y_fixed': 5.14, '1y_fixed': 6.10}})
    assert res['rbc'].quality == 'posted_ok'
    assert any('5y_fixed moved 5.14 -> 6.09' in a for a in res['rbc'].alerts)
    assert not any(a.startswith('1y_fixed') for a in res['rbc'].alerts)
    special = run([RBC], Pages({RBC.url: '<p>5 Year Fixed 4.49%</p>'}), robots(), DAY)
    assess(special, DAY, ref('6.19'), {})
    assert special['rbc'].quality == 'likely_special_offer'


def test_save_and_previous_rates(tmp_path):
    res = run([RBC], Pages({RBC.url: (F / 'rbc.html').read_text()}), robots(), date(2026, 10, 11))
    assess(res, date(2026, 10, 11), ref(), {})
    save(res, date(2026, 10, 11), tmp_path)
    header = (tmp_path / 'history.csv').read_text().splitlines()[0]
    assert header == 'date,lender,term,rate_pct,quality'
    prev = previous_rates(tmp_path, DAY)
    assert prev['rbc']['5y_fixed'] == 6.09
    assert previous_rates(tmp_path, date(2026, 10, 11)) == {}


def test_user_agent_contact(monkeypatch):
    monkeypatch.setenv('RR_SCRAPER_CONTACT', 'mailto:rates@example.ca')
    assert 'mailto:rates@example.ca' in user_agent()
