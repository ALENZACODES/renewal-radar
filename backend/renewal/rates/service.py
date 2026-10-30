"""Process-wide access to the reference rate book and workbench helpers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from .pipeline import build
from .series import Lookup, RateBook

REFERENCE_DIR = Path(__file__).resolve().parents[3] / 'data' / 'reference'


@lru_cache(maxsize=1)
def reference_book(directory: str = str(REFERENCE_DIR)) -> RateBook:
    return RateBook(build(Path(directory)))


def workbench_rates(book: RateBook, lender: str, funding: date, payout: date,
                    original_term_months: int) -> dict:
    """Posted rate at funding and the posted table at payout, with provenance.

    Returns a dict ready to merge into a workbench request: ``original_posted_rate``
    and ``current_posted`` plus the evidence for each, so the UI can show where
    every number came from and whether it is a lender figure or a market proxy.
    """
    original: Lookup | None = book.posted_at(lender, original_term_months, funding)
    table = book.table_at(lender, payout)
    return {
        'original_posted_rate': None if original is None else original.rate,
        'original_evidence': None if original is None else original.as_dict(),
        'current_posted': {term: hit.rate for term, hit in table.items()},
        'current_evidence': {str(term): hit.as_dict() for term, hit in table.items()},
        'uses_proxy': bool((original and original.proxy) or any(h.proxy for h in table.values())),
    }


def as_strings(rates: dict[int, Decimal]) -> dict[str, str]:
    return {str(k): str(v) for k, v in rates.items()}
