"""Mask account identifiers before text is stored, logged or shown.

Masks long digit runs (account, transit and card numbers, SINs) but leaves
money amounts, percentages, dates and short reference numbers readable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Card or account numbers: 8+ digits possibly grouped by spaces or dashes,
# not part of an amount (no $ before, no decimal point after).
_LONG_ID = re.compile(r'(?<![\d$.,])(?:\d[ -]?){7,}\d(?![\d.,%]|\s?%)')
_SIN = re.compile(r'(?<!\d)\d{3}[ -]\d{3}[ -]\d{3}(?!\d)')
_LABELLED = re.compile(r'((?:account|acct|mortgage|loan|compte|prêt|transit|folio)\s*(?:no\.?|number|#|n[o°º]\.?)?\s*[:#]?\s*)'
                       r'([A-Z0-9][A-Z0-9 -]{4,}[A-Z0-9])', re.I)


@dataclass(frozen=True)
class Redaction:
    text: str
    masked: int


def _mask(value: str) -> str:
    digits = [c for c in value if c.isalnum()]
    keep = ''.join(digits[-4:])
    return '•' * max(4, len(digits) - 4) + keep


def redact(text: str) -> Redaction:
    count = 0

    def labelled(m: re.Match[str]) -> str:
        nonlocal count
        if not any(c.isdigit() for c in m.group(2)):
            return m.group(0)
        count += 1
        return m.group(1) + _mask(m.group(2))

    def plain(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _mask(m.group(0))

    out = _LABELLED.sub(labelled, text)
    out = _SIN.sub(plain, out)
    out = _LONG_ID.sub(lambda m: m.group(0) if '•' in m.group(0) else plain(m), out)
    return Redaction(out, count)
