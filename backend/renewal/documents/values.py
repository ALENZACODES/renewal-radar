"""Parse money, percentages, dates and durations written in English or French."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

D = Decimal

MONTHS_EN = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
     'september', 'october', 'november', 'december'], start=1)}
MONTHS_FR = {m: i for i, m in enumerate(
    ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
     'septembre', 'octobre', 'novembre', 'décembre'], start=1)}
_ASCII_FR = {'fevrier': 2, 'aout': 8, 'decembre': 12}

# 450,000.00 | $450,000 | 450 000,00 $ | 450 000 $ | 450.000,00
MONEY = re.compile(r'(?:\$\s?)?(\d{1,3}(?:[ ,.\u202f\u00a0]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)\s?\$?')
PERCENT = re.compile(r'(\d{1,2}(?:[.,]\d{1,4})?)\s?%')
ISO = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
NUMERIC = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')
TEXT_EN = re.compile(r'\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b')
TEXT_EN_DMY = re.compile(r'\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b')
TEXT_FR = re.compile(r'\b(\d{1,2})(?:er)?\s+([a-zéèûô]{3,9})\.?\s+(\d{4})\b', re.I)
YEARS_MONTHS = re.compile(r'(\d{1,2})[\s-]*(?:years?|yrs?|ans?|années?)(?:\s*(?:and|et|,)?\s*(\d{1,2})\s*(?:months?|mois))?', re.I)
MONTHS_ONLY = re.compile(r'(\d{1,3})\s*(?:months?|mois)\b', re.I)
WORD_YEARS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'seven': 7, 'ten': 10,
              'un': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5, 'sept': 7, 'dix': 10}


def parse_money(text: str) -> D | None:
    """First amount in ``text``. Handles English and French grouping and decimals."""
    for m in MONEY.finditer(text):
        raw = m.group(1).replace('\u202f', ' ').replace('\u00a0', ' ')
        if re.search(r',\d{2}$', raw):                # French decimal comma
            raw = raw[:-3].replace(' ', '').replace('.', '') + '.' + raw[-2:]
        else:
            raw = raw.replace(',', '').replace(' ', '')
            if raw.count('.') > 1:                    # 450.000 grouped with points
                raw = raw.replace('.', '')
        try:
            value = D(raw)
        except InvalidOperation:
            continue
        if '$' in m.group(0) or value >= 100:
            return value
    return None


def parse_percent(text: str) -> D | None:
    m = PERCENT.search(text)
    if not m:
        return None
    value = D(m.group(1).replace(',', '.'))
    return value if D('0') < value <= D('30') else None


def _month(name: str) -> int | None:
    key = name.lower().rstrip('.')
    if key in MONTHS_FR:
        return MONTHS_FR[key]
    if key in _ASCII_FR:
        return _ASCII_FR[key]
    for full, number in MONTHS_EN.items():
        if len(key) >= 3 and full.startswith(key):
            return number
    return None


def parse_date(text: str, *, day_first: bool = False) -> date | None:
    """First date in ``text``. ``day_first`` decides ambiguous ``dd/mm/yyyy`` forms."""
    candidates: list[tuple[int, date]] = []
    for m in ISO.finditer(text):
        try:
            candidates.append((m.start(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        except ValueError:
            pass
    for m in NUMERIC.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (a, b) if day_first or a > 12 else (b, a)
        try:
            candidates.append((m.start(), date(y, month, day)))
        except ValueError:
            pass
    for m in TEXT_EN.finditer(text):
        month = _month(m.group(1))
        if month:
            try:
                candidates.append((m.start(), date(int(m.group(3)), month, int(m.group(2)))))
            except ValueError:
                pass
    for pattern in (TEXT_FR, TEXT_EN_DMY):
        for m in pattern.finditer(text):
            month = _month(m.group(2))
            if month:
                try:
                    candidates.append((m.start(), date(int(m.group(3)), month, int(m.group(1)))))
                except ValueError:
                    pass
    return min(candidates)[1] if candidates else None


def parse_months(text: str) -> int | None:
    """Duration in months from '19 years 3 months', '25 ans', '60 months', 'five-year'."""
    m = YEARS_MONTHS.search(text)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2) or 0)
    m = MONTHS_ONLY.search(text)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(' + '|'.join(WORD_YEARS) + r')[- ](?:year|yr|ans?)\b', text, re.I)
    if m:
        return WORD_YEARS[m.group(1).lower()] * 12
    return None


def iso(value: date | datetime) -> str:
    return value.isoformat()
