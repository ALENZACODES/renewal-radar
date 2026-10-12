"""Public rate pages the scraper is allowed to read, one entry per lender."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LenderSource:
    code: str
    name: str
    url: str
    prime_label: str = r'\bprime rate\b'
    needs_javascript: bool = True
    notes: str = ''


SOURCES: tuple[LenderSource, ...] = (
    LenderSource('rbc', 'RBC Royal Bank', 'https://www.rbcroyalbank.com/mortgages/mortgage-rates.html',
                 r'\bRBC Royal Bank prime rate\b|\bprime rate\b'),
    LenderSource('td', 'TD Canada Trust',
                 'https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates',
                 r'\bTD Mortgage Prime Rate\b|\bprime rate\b'),
    LenderSource('bmo', 'BMO', 'https://www.bmo.com/main/personal/mortgages/mortgage-rates/'),
    LenderSource('scotia', 'Scotiabank',
                 'https://www.scotiabank.com/ca/en/personal/rates-prices/mortgages-rates.html'),
    LenderSource('cibc', 'CIBC', 'https://www.cibc.com/en/personal-banking/mortgages/mortgage-rates.html'),
    LenderSource('national', 'National Bank', 'https://www.nbc.ca/personal/mortgages/rates.html'),
    LenderSource('tangerine', 'Tangerine', 'https://www.tangerine.ca/en/rates/mortgage-rates',
                 notes='Publishes discounted rates; posted rates are not shown.'),
    LenderSource('eq', 'EQ Bank', 'https://www.eqbank.com/personal-banking/mortgages',
                 notes='Monoline-style pricing; treat figures as offered, not posted.'),
)

BY_CODE: dict[str, LenderSource] = {s.code: s for s in SOURCES}


def source(code: str) -> LenderSource:
    try:
        return BY_CODE[code.lower()]
    except KeyError:
        raise KeyError(f'unknown lender {code!r}; known: {", ".join(sorted(BY_CODE))}') from None
