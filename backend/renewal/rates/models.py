"""Typed rate observation shared by every loader."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

D = Decimal

# Term codes used by the lender parsers and the reference CSVs.
TERM_MONTHS: dict[str, int] = {
    '1y_fixed': 12, '2y_fixed': 24, '3y_fixed': 36, '4y_fixed': 48, '5y_fixed': 60,
    '7y_fixed': 84, '10y_fixed': 120,
}
VARIABLE_CODES = {'variable_5y': 60}
PRIME = 'prime'
CHARTERED = 'chartered_banks'   # lender name for Bank of Canada / StatCan aggregates


class Quality(str, Enum):
    OFFICIAL = 'official'                         # statistical agency series
    POSTED_OK = 'posted_ok'                       # lender page, 5y within tolerance of BoC posted
    LIKELY_SPECIAL = 'likely_special_offer'       # lender page shows a discounted rate
    UNVERIFIED = 'unverified'                     # no 5y on the capture to check against


def term_code_to_months(code: str) -> tuple[int | None, str]:
    """``'5y_fixed'`` -> ``(60, 'fixed')``; ``'prime'`` -> ``(None, 'prime')``."""
    if code in TERM_MONTHS:
        return TERM_MONTHS[code], 'fixed'
    if code in VARIABLE_CODES:
        return VARIABLE_CODES[code], 'variable'
    if code == PRIME:
        return None, 'prime'
    raise ValueError(f'unknown term code {code!r}')


@dataclass(frozen=True)
class Observation:
    observed: date
    lender: str
    term_months: int | None
    rate_type: str              # fixed | variable | prime
    rate: D
    source_id: str
    source_url: str
    quality: Quality

    def __post_init__(self) -> None:
        if not self.lender:
            raise ValueError('lender is required')
        if self.rate_type not in ('fixed', 'variable', 'prime'):
            raise ValueError(f'unknown rate_type {self.rate_type!r}')
        if self.rate < 0 or self.rate > 30:
            raise ValueError(f'rate {self.rate} outside 0..30 percentage points')
        if self.term_months is not None and not 1 <= self.term_months <= 360:
            raise ValueError('term_months must be within 1..360')
        if self.rate_type == 'prime' and self.term_months is not None:
            raise ValueError('prime observations carry no term')

    def sort_key(self) -> tuple:
        return (self.observed, self.lender, self.rate_type, self.term_months or 0, self.source_id)

    @property
    def key(self) -> tuple[str, str, int | None]:
        return self.lender, self.rate_type, self.term_months

    def as_row(self) -> dict[str, str]:
        return {'date': self.observed.isoformat(), 'lender': self.lender,
                'rate_type': self.rate_type,
                'term_months': '' if self.term_months is None else str(self.term_months),
                'rate_pct': str(self.rate), 'source_id': self.source_id,
                'source_url': self.source_url, 'quality': self.quality.value}
