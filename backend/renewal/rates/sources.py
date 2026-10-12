"""Loaders for each public rate source. Every loader yields ``Observation``s."""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator

from .models import CHARTERED, Observation, Quality, term_code_to_months

D = Decimal

VALET_URL = 'https://www.bankofcanada.ca/valet/observations/{sid}/csv'
STATCAN_URL = 'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410014501'

# Bank of Canada series id -> (term months, rate type)
VALET_SERIES: dict[str, tuple[int | None, str]] = {
    'V80691333': (12, 'fixed'),
    'V80691334': (36, 'fixed'),
    'V80691335': (60, 'fixed'),
    'V80691311': (None, 'prime'),
}


def _decimal(text: str) -> D | None:
    text = (text or '').strip().strip('"')
    if not text:
        return None
    try:
        return D(text)
    except InvalidOperation:
        return None


def parse_valet_csv(text: str, series_id: str | None = None) -> Iterator[Observation]:
    """Parse a Valet CSV download. Metadata blocks before ``"OBSERVATIONS"`` are skipped."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip('"').startswith('date'))
    except StopIteration:
        raise ValueError('no OBSERVATIONS header in Valet CSV') from None
    reader = csv.reader(lines[start:])
    header = next(reader)
    columns = header[1:]
    if series_id is not None and series_id not in columns:
        raise ValueError(f'series {series_id} not in file (found {columns})')
    for row in reader:
        if not row or not row[0].strip():
            continue
        observed = date.fromisoformat(row[0].strip())
        for sid, cell in zip(columns, row[1:]):
            if sid not in VALET_SERIES or (series_id and sid != series_id):
                continue
            rate = _decimal(cell)
            if rate is None:
                continue
            term, kind = VALET_SERIES[sid]
            yield Observation(observed, CHARTERED, term, kind, rate, sid,
                              VALET_URL.format(sid=sid), Quality.OFFICIAL)


def parse_statcan_csv(text: str) -> Iterator[Observation]:
    """Table 34-10-0145 (monthly 5-year conventional). REF_DATE ``YYYY-MM`` maps to the 1st."""
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    for row in reader:
        rate = _decimal(row.get('VALUE', ''))
        if rate is None:
            continue
        year, month = (int(x) for x in row['REF_DATE'].split('-')[:2])
        vector = row.get('VECTOR', 'v733833')
        yield Observation(date(year, month, 1), CHARTERED, 60, 'fixed', rate,
                          f'StatCan 34-10-0145 {vector}', STATCAN_URL, Quality.OFFICIAL)


_QUALITY = {'posted_ok': Quality.POSTED_OK, 'likely_special_offer': Quality.LIKELY_SPECIAL}


def parse_lender_csv(text: str, default_source: str = 'lender_page') -> Iterator[Observation]:
    """Lender rows ``date,lender,term,rate_pct[,snapshot_url][,quality]``.

    Used for the validated archive CSV and the daily scraper history. Rows without a
    quality column are ``unverified`` until :func:`renewal.rates.validate.classify` runs.
    """
    for row in csv.DictReader(io.StringIO(text)):
        rate = _decimal(row.get('rate_pct', ''))
        if rate is None:
            continue
        term, kind = term_code_to_months(row['term'].strip())
        quality = _QUALITY.get((row.get('quality') or '').strip(), Quality.UNVERIFIED)
        url = (row.get('snapshot_url') or '').strip()
        yield Observation(date.fromisoformat(row['date'].strip()), row['lender'].strip().lower(),
                          term, kind, rate, 'wayback' if 'web.archive.org' in url else default_source,
                          url, quality)


def load_reference_dir(directory: Path) -> list[Observation]:
    """Load every known file in a reference directory; missing files are skipped."""
    out: list[Observation] = []
    for sid in VALET_SERIES:
        path = directory / f'boc_{sid}.csv'
        if path.exists():
            out.extend(parse_valet_csv(path.read_text(encoding='utf-8'), sid))
    statcan = directory / '34100145.csv'
    if statcan.exists():
        out.extend(parse_statcan_csv(statcan.read_text(encoding='utf-8-sig')))
    for name in ('lender_posted_rates_wayback_validated.csv', 'scraper_history.csv'):
        path = directory / name
        if path.exists():
            out.extend(parse_lender_csv(path.read_text(encoding='utf-8'),
                                        'scraper' if name.startswith('scraper') else 'lender_page'))
    return out


def dedupe(observations: Iterable[Observation]) -> list[Observation]:
    """Keep one observation per (date, lender, type, term, source), preferring better quality."""
    rank = {Quality.OFFICIAL: 0, Quality.POSTED_OK: 1, Quality.UNVERIFIED: 2, Quality.LIKELY_SPECIAL: 3}
    best: dict[tuple, Observation] = {}
    for obs in observations:
        k = (obs.observed, obs.lender, obs.rate_type, obs.term_months, obs.source_id)
        cur = best.get(k)
        if cur is None or rank[obs.quality] < rank[cur.quality]:
            best[k] = obs
    return sorted(best.values(), key=Observation.sort_key)
