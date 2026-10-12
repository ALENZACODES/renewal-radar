"""Label-anchored field extraction with page and line evidence.

For each field the extractor looks for a label, then reads the value from the
rest of that line, or from the next non-empty line when statements lay fields
out as a two-row table. Confidence reflects where the value was found and
whether the page came from OCR.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from .labels import FIELDS, FREQUENCIES, FieldSpec, compiled
from .text import PageText
from .values import parse_date, parse_money, parse_months, parse_percent

D = Decimal
SAME_LINE, NEXT_LINE, OCR_PENALTY = 0.9, 0.75, 0.1


@dataclass(frozen=True)
class FieldHit:
    name: str
    value: Any
    page: int
    line: int
    excerpt: str
    language: str
    confidence: float

    def as_dict(self) -> dict:
        value = self.value
        if isinstance(value, D):
            value = str(value)
        elif hasattr(value, 'isoformat'):
            value = value.isoformat()
        return {'value': value, 'page': self.page, 'line': self.line, 'excerpt': self.excerpt,
                'language': self.language, 'confidence': round(self.confidence, 2)}


def _frequency(text: str) -> str | None:
    for pattern, value in FREQUENCIES:
        if re.search(pattern, text, re.I):
            return value
    return None


def _rate_type(text: str) -> str | None:
    if re.search(r'\bvariable\b|\badjustable\b|prime\s*[+-]|taux\s+variable', text, re.I):
        return 'variable'
    if re.search(r'\bfixed\b|taux\s+fixe|\bfixe\b', text, re.I):
        return 'fixed'
    return None


def _bounded_money(lo: D, hi: D) -> Callable[[str], D | None]:
    def parse(text: str) -> D | None:
        value = parse_money(text)
        return value if value is not None and lo <= value <= hi else None
    return parse


def _bounded_months(lo: int, hi: int) -> Callable[[str], int | None]:
    def parse(text: str) -> int | None:
        value = parse_months(text)
        return value if value is not None and lo <= value <= hi else None
    return parse


PARSERS: dict[str, Callable[[str], Any]] = {
    'balance': _bounded_money(D('1000'), D('50000000')),
    'payment': _bounded_money(D('50'), D('500000')),
    'rate_pct': parse_percent,
    'renewal_rate_pct': parse_percent,
    'prepayment_lump_sum_pct': lambda t: (v if (v := parse_percent(t)) is not None and v <= 100 else None),
    'maturity_date': parse_date,
    'term_months': _bounded_months(6, 120),
    'amortization_months': _bounded_months(12, 480),
    'frequency': _frequency,
    'rate_type': _rate_type,
}


def _find(spec: FieldSpec, pages: tuple[PageText, ...]) -> FieldHit | None:
    parse = PARSERS[spec.name]
    patterns = compiled(spec)
    for page in pages:
        lines = page.text.splitlines()
        for i, line in enumerate(lines):
            for lang, pattern in patterns:
                m = pattern.search(line)
                if not m:
                    continue
                rest = line[m.end():]
                value = parse(rest)
                conf = SAME_LINE
                if value is None:
                    nxt = next((l for l in lines[i + 1:i + 3] if l.strip()), '')
                    value = parse(nxt)
                    conf = NEXT_LINE
                if value is None:
                    continue
                if page.method == 'ocr':
                    conf -= OCR_PENALTY
                return FieldHit(spec.name, value, page.page, i + 1, line.strip()[:160], lang, conf)
    return None


def _document_rate_type(pages: tuple[PageText, ...]) -> FieldHit | None:
    for page in pages:
        for i, line in enumerate(page.text.splitlines()):
            if re.search(r'\b(?:\d{1,2}|one|two|three|four|five|seven|ten)[- ](?:year|yr)\b[^\n]{0,20}'
                         r'\b(?:fixed|variable)\b|taux\s+(?:fixe|variable)', line, re.I):
                value = _rate_type(line)
                if value:
                    return FieldHit('rate_type', value, page.page, i + 1, line.strip()[:160],
                                    'fr' if 'taux' in line.lower() else 'en', 0.7)
    return None


def extract_fields(pages: tuple[PageText, ...]) -> dict[str, FieldHit]:
    hits: dict[str, FieldHit] = {}
    for spec in FIELDS:
        hit = _find(spec, pages)
        if hit is not None:
            hits[spec.name] = hit
    if 'rate_type' not in hits:
        fallback = _document_rate_type(pages)
        if fallback is not None:
            hits['rate_type'] = fallback
    return hits


def required_missing(hits: dict[str, FieldHit]) -> list[str]:
    return [f.name for f in FIELDS if f.required and f.name not in hits]
