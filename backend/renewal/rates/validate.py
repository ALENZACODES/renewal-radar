"""Classify lender-page observations as posted rates or likely special offers.

Bank pages often lead with discounted "special" rates. An IRD needs the posted
rate, so each lender capture is checked against the Bank of Canada chartered-bank
posted 5-year rate for the same week: if the capture's own 5-year fixed rate is
within ``tolerance`` percentage points, the whole capture is treated as posted.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from .models import CHARTERED, Observation, Quality

D = Decimal
DEFAULT_TOLERANCE = D('0.60')
MAX_REFERENCE_AGE_DAYS = 45


class Reference:
    """Step function over a chartered-bank series for fast as-of lookups."""

    def __init__(self, observations: Iterable[Observation]):
        pts = sorted((o.observed, o.rate) for o in observations)
        self.dates: list[date] = [d for d, _ in pts]
        self.rates: list[D] = [r for _, r in pts]

    def at(self, day: date, max_age_days: int = MAX_REFERENCE_AGE_DAYS) -> D | None:
        i = bisect.bisect_right(self.dates, day) - 1
        if i < 0 or (day - self.dates[i]).days > max_age_days:
            return None
        return self.rates[i]


def boc_five_year(observations: Iterable[Observation]) -> Reference:
    return Reference(o for o in observations
                     if o.lender == CHARTERED and o.term_months == 60 and o.rate_type == 'fixed'
                     and o.source_id == 'V80691335')


def classify(observations: Sequence[Observation], reference: Reference,
             tolerance: D = DEFAULT_TOLERANCE) -> list[Observation]:
    """Return lender observations with ``quality`` set; official rows pass through."""
    captures: dict[tuple[str, date, str], dict[tuple[str, int | None], Observation]] = defaultdict(dict)
    for o in observations:
        if o.quality is not Quality.OFFICIAL:
            captures[(o.lender, o.observed, o.source_url)][(o.rate_type, o.term_months)] = o
    out: list[Observation] = [o for o in observations if o.quality is Quality.OFFICIAL]
    for (_, day, _), rows in captures.items():
        five = rows.get(('fixed', 60))
        ref = reference.at(day)
        if five is None or ref is None:
            quality = Quality.UNVERIFIED
        elif abs(five.rate - ref) <= tolerance:
            quality = Quality.POSTED_OK
        else:
            quality = Quality.LIKELY_SPECIAL
        out.extend(replace(o, quality=quality) for o in rows.values())
    return sorted(out, key=Observation.sort_key)


def quality_report(observations: Iterable[Observation]) -> dict[str, dict[str, int | str]]:
    """Per-lender counts by quality with first and last observation dates."""
    report: dict[str, dict[str, int | str]] = {}
    for o in observations:
        r = report.setdefault(o.lender, {'rows': 0, 'first': o.observed.isoformat(),
                                         'last': o.observed.isoformat()})
        r['rows'] = int(r['rows']) + 1
        r[o.quality.value] = int(r.get(o.quality.value, 0)) + 1
        r['first'] = min(str(r['first']), o.observed.isoformat())
        r['last'] = max(str(r['last']), o.observed.isoformat())
    return dict(sorted(report.items()))
