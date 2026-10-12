"""Identify the lender from letterhead and body text."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import PageText

# code, display name, patterns. Codes match the penalty profiles where they exist.
LENDERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('rbc', 'RBC Royal Bank', (r'\bRBC\b', r'Royal Bank of Canada', r'Banque Royale')),
    ('td', 'TD Canada Trust', (r'\bTD Canada Trust\b', r'Toronto[- ]Dominion', r'\bTD Bank\b', r'\bTD\b')),
    ('bmo', 'BMO', (r'\bBMO\b', r'Bank of Montreal', r'Banque de Montréal')),
    ('scotia', 'Scotiabank', (r'Scotiabank', r'Bank of Nova Scotia', r'Scotia Mortgage', r'Banque Scotia')),
    ('cibc', 'CIBC', (r'\bCIBC\b', r'Canadian Imperial Bank')),
    ('nbc', 'National Bank', (r'National Bank of Canada', r'Banque Nationale', r'\bNBC\b')),
    ('desjardins', 'Desjardins', (r'Desjardins',)),
    ('tangerine', 'Tangerine', (r'Tangerine',)),
    ('first_national', 'First National', (r'First National Financial', r'First National')),
    ('mcap', 'MCAP', (r'\bMCAP\b',)),
    ('eq', 'Equitable Bank', (r'Equitable Bank', r'\bEQ Bank\b')),
    ('hsbc', 'HSBC', (r'\bHSBC\b',)),
    ('simplii', 'Simplii Financial', (r'Simplii',)),
    ('laurentian', 'Laurentian Bank', (r'Laurentian Bank', r'Banque Laurentienne')),
    ('atb', 'ATB Financial', (r'\bATB\b',)),
    ('manulife', 'Manulife Bank', (r'Manulife',)),
)


@dataclass(frozen=True)
class LenderMatch:
    code: str
    name: str
    score: float
    evidence: str


def identify(pages: tuple[PageText, ...]) -> LenderMatch | None:
    """Score each lender: letterhead (first 8 lines of page 1) counts triple."""
    if not pages:
        return None
    head = '\n'.join(pages[0].text.splitlines()[:8])
    body = '\n'.join(p.text for p in pages)
    best: LenderMatch | None = None
    for code, name, patterns in LENDERS:
        score = 0.0
        evidence = ''
        for pattern in patterns:
            rx = re.compile(pattern)
            in_head = len(rx.findall(head))
            in_body = len(rx.findall(body))
            if in_body and not evidence:
                m = rx.search(body)
                evidence = body[max(0, m.start() - 30): m.end() + 30].replace('\n', ' ') if m else ''
            score += in_head * 3 + in_body
        if score and (best is None or score > best.score):
            best = LenderMatch(code, name, score, evidence.strip())
    return best
