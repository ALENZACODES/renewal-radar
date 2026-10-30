"""Daily polite scrape: robots-checked, spaced out, once per lender per day.

    PYTHONPATH=backend python -m renewal.scraper.runner --out data/current

Each run writes ``YYYY-MM-DD.json`` (status, rates and evidence per lender) and
appends to ``history.csv``. Rates are then checked against the Bank of Canada
posted 5-year rate and against the previous run, so a page redesign that starts
returning special offers is flagged instead of entering penalty math.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Sequence

from ..rates.models import Observation, Quality, term_code_to_months
from ..rates.validate import Reference, classify
from .fetch import Fetcher, user_agent
from .lenders import SOURCES, LenderSource
from .parse import ParsedRate, parse_page
from .robots import RobotsPolicy

MIN_SPACING_SECONDS = 10.0
JUMP_ALERT_PP = Decimal('0.50')


@dataclass
class LenderRun:
    code: str
    status: str                       # ok | no_rates_parsed | skipped_robots | skipped_today | error
    url: str
    rates: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    quality: str | None = None
    alerts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {'status': self.status, 'url': self.url, 'rates': self.rates}
        for key in ('evidence', 'error', 'quality', 'alerts'):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


def already_ran(out_dir: Path, day: date) -> set[str]:
    path = out_dir / f'{day.isoformat()}.json'
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding='utf-8'))
    return {code for code, r in data.items() if r.get('status') in ('ok', 'no_rates_parsed')}


def previous_rates(out_dir: Path, before: date) -> dict[str, dict[str, float]]:
    history = out_dir / 'history.csv'
    latest: dict[str, dict[str, tuple[str, float]]] = {}
    if not history.exists():
        return {}
    with history.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['date'] >= before.isoformat():
                continue
            terms = latest.setdefault(row['lender'], {})
            prior = terms.get(row['term'])
            if prior is None or row['date'] >= prior[0]:
                terms[row['term']] = (row['date'], float(row['rate_pct']))
    return {lender: {t: v for t, (_, v) in terms.items()} for lender, terms in latest.items()}


def run(sources: Sequence[LenderSource], fetcher: Fetcher, robots: RobotsPolicy, day: date, *,
        skip: Iterable[str] = (), sleep: Callable[[float], None] = time.sleep,
        spacing: float = MIN_SPACING_SECONDS) -> dict[str, LenderRun]:
    results: dict[str, LenderRun] = {}
    skip = set(skip)
    fetched_any = False
    for src in sources:
        if src.code in skip:
            results[src.code] = LenderRun(src.code, 'skipped_today', src.url)
            continue
        if not robots.allowed(src.url):
            results[src.code] = LenderRun(src.code, 'skipped_robots', src.url)
            continue
        if fetched_any:
            sleep(max(spacing, robots.crawl_delay(src.url) or 0.0))
        fetched_any = True
        try:
            parsed: dict[str, ParsedRate] = parse_page(fetcher.get(src.url), src.prime_label)
        except Exception as exc:
            results[src.code] = LenderRun(src.code, 'error', src.url, error=f'{type(exc).__name__}: {exc}'[:300])
            continue
        results[src.code] = LenderRun(
            src.code, 'ok' if parsed else 'no_rates_parsed', src.url,
            rates={t: p.rate for t, p in parsed.items()},
            evidence={t: p.evidence for t, p in parsed.items()})
    return results


def assess(results: dict[str, LenderRun], day: date, reference: Reference,
           previous: dict[str, dict[str, float]]) -> None:
    """Attach a posted/special quality verdict and day-over-day jump alerts in place."""
    for code, r in results.items():
        if not r.rates:
            continue
        observations = []
        for term, rate in r.rates.items():
            months, kind = term_code_to_months(term)
            observations.append(Observation(day, code, months, kind, Decimal(str(rate)), 'scraper',
                                            r.url, Quality.UNVERIFIED))
        classified = classify(observations, reference)
        r.quality = classified[0].quality.value
        for term, rate in r.rates.items():
            old = previous.get(code, {}).get(term)
            if old is not None and abs(Decimal(str(rate)) - Decimal(str(old))) >= JUMP_ALERT_PP:
                r.alerts.append(f'{term} moved {old} -> {rate}; check for a page change before use')


def save(results: dict[str, LenderRun], day: date, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{day.isoformat()}.json'
    merged: dict[str, dict] = {}
    if path.exists():
        merged = json.loads(path.read_text(encoding='utf-8'))
    for code, r in results.items():
        if r.status != 'skipped_today':
            merged[code] = r.as_dict()
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    history = out_dir / 'history.csv'
    new = not history.exists()
    with history.open('a', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        if new:
            w.writerow(['date', 'lender', 'term', 'rate_pct', 'quality'])
        for code, r in results.items():
            if r.status == 'ok':
                for term, rate in sorted(r.rates.items()):
                    w.writerow([day.isoformat(), code, term, rate, r.quality or 'unverified'])
    return path


def main(argv: Sequence[str] | None = None) -> int:
    from ..rates.service import reference_book
    from ..rates.validate import boc_five_year
    from .fetch import BrowserFetcher, HttpFetcher

    ap = argparse.ArgumentParser(description='Polite daily posted-rate scrape')
    ap.add_argument('--out', type=Path, default=Path('data/current'))
    ap.add_argument('--lenders', nargs='*', help='lender codes (default: all)')
    ap.add_argument('--browser', action='store_true', help='render with headless Chromium')
    args = ap.parse_args(argv)
    sources = [s for s in SOURCES if not args.lenders or s.code in args.lenders]
    http = HttpFetcher()
    fetcher: Fetcher = BrowserFetcher() if args.browser else http
    robots = RobotsPolicy(user_agent(), http.get)
    day = date.today()
    results = run(sources, fetcher, robots, day, skip=already_ran(args.out, day))
    book = reference_book()
    reference = boc_five_year(o for o in book.series('chartered_banks', 60))
    assess(results, day, reference, previous_rates(args.out, day))
    save(results, day, args.out)
    print(json.dumps({c: r.status for c, r in results.items()}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
