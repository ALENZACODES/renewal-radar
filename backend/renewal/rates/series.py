"""As-of lookups over posted-rate history.

``RateBook`` answers the two questions the penalty workbench needs:

* what was the posted rate for this lender and term on the funding date?
* what is the posted table (term -> rate) for this lender today?

Only ``official`` and ``posted_ok`` observations are used. When a lender has no
usable observation, the Bank of Canada chartered-bank series is offered as an
explicitly labelled proxy rather than silently substituted.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from .models import CHARTERED, Observation, Quality

D = Decimal
USABLE = frozenset({Quality.OFFICIAL, Quality.POSTED_OK})


@dataclass(frozen=True)
class Lookup:
    rate: D
    observed: date
    lender: str
    term_months: int | None
    source_id: str
    source_url: str
    quality: Quality
    age_days: int
    proxy: bool

    def as_dict(self) -> dict:
        return {'rate': str(self.rate), 'observed': self.observed.isoformat(),
                'lender': self.lender, 'term_months': self.term_months,
                'source_id': self.source_id, 'source_url': self.source_url,
                'quality': self.quality.value, 'age_days': self.age_days, 'proxy': self.proxy}


class RateBook:
    def __init__(self, observations: Iterable[Observation]):
        grouped: dict[tuple[str, str, int | None], list[Observation]] = defaultdict(list)
        for o in observations:
            if o.quality in USABLE:
                grouped[o.key].append(o)
        self._series: dict[tuple[str, str, int | None], list[Observation]] = {}
        self._dates: dict[tuple[str, str, int | None], list[date]] = {}
        for key, rows in grouped.items():
            # Prefer the weekly Valet series over monthly StatCan on the same day.
            rows.sort(key=lambda o: (o.observed, o.source_id.startswith('V')))
            self._series[key] = rows
            self._dates[key] = [o.observed for o in rows]

    @property
    def lenders(self) -> list[str]:
        return sorted({k[0] for k in self._series})

    def terms(self, lender: str, rate_type: str = 'fixed') -> list[int]:
        return sorted(k[2] for k in self._series
                      if k[0] == lender and k[1] == rate_type and k[2] is not None)

    def _at(self, key: tuple[str, str, int | None], day: date, max_age_days: int) -> Observation | None:
        dates = self._dates.get(key)
        if not dates:
            return None
        i = bisect.bisect_right(dates, day) - 1
        if i < 0:
            return None
        obs = self._series[key][i]
        return obs if (day - obs.observed).days <= max_age_days else None

    def posted_at(self, lender: str, term_months: int, day: date, *, rate_type: str = 'fixed',
                  max_age_days: int = 120, allow_proxy: bool = True) -> Lookup | None:
        """Latest usable posted rate on or before ``day`` within ``max_age_days``."""
        lender = lender.lower()
        obs = self._at((lender, rate_type, term_months), day, max_age_days)
        proxy = False
        if obs is None and allow_proxy and lender != CHARTERED:
            obs = self._at((CHARTERED, rate_type, term_months), day, max_age_days)
            proxy = obs is not None
        if obs is None:
            return None
        return Lookup(obs.rate, obs.observed, obs.lender, obs.term_months, obs.source_id,
                      obs.source_url, obs.quality, (day - obs.observed).days, proxy)

    def table_at(self, lender: str, day: date, *, max_age_days: int = 120,
                 allow_proxy: bool = True) -> dict[int, Lookup]:
        """Posted fixed-rate table for ``lender`` on ``day``; proxy terms fill gaps."""
        lender = lender.lower()
        terms = set(self.terms(lender))
        if allow_proxy:
            terms |= set(self.terms(CHARTERED))
        out: dict[int, Lookup] = {}
        for term in sorted(terms):
            hit = self.posted_at(lender, term, day, max_age_days=max_age_days, allow_proxy=allow_proxy)
            if hit is not None:
                out[term] = hit
        return out

    def series(self, lender: str, term_months: int | None, rate_type: str = 'fixed',
               start: date | None = None, end: date | None = None) -> list[Observation]:
        rows = self._series.get((lender.lower(), rate_type, term_months), [])
        return [o for o in rows if (start is None or o.observed >= start)
                and (end is None or o.observed <= end)]
