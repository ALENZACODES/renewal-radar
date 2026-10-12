"""Extract posted mortgage rates from a lender rate page.

Two passes, in order of reliability:

1. **Rows.** Table rows and card-like blocks are read as units. A row whose
   label names a term ("5 Year Fixed", "Fixed rate: 3-year", "Closed 1 Year")
   contributes the rate in the column headed "posted" when there is one, else
   the first rate in the row. Variable rows written as "Prime + 0.10% = 4.55%"
   contribute the effective rate, never the spread.
2. **Text.** For pages without usable structure, the first percentage within a
   short window after a term label is used.

Scripts, styles and templates are removed first so embedded JSON or tracking
values can't leak in. Every returned rate carries the text it came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from bs4 import BeautifulSoup, Tag

PCT = re.compile(r'(?<![\d.])(\d{1,2}\.\d{2,3})\s?%')
WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'seven': 7, 'ten': 10}
FIXED_TERMS = (1, 2, 3, 4, 5, 7, 10)
_NUM = r'(?:10|[1-57]|one|two|three|four|five|seven|ten)'
TERM = re.compile(rf'(?<![\d.]){_NUM}[- ]?(?:years?|yrs?)\b', re.I)
VARIABLE = re.compile(r'\bvariable\b|\badjustable\b', re.I)
FIXED = re.compile(r'\bfixed\b|\bclosed\b', re.I)
SPECIAL = re.compile(r'\bspecial\b|\bpromo|\blimited[- ]time\b|\bdiscount', re.I)
MIN_RATE, MAX_RATE, MIN_PRIME = 0.5, 25.0, 2.0


@dataclass(frozen=True)
class ParsedRate:
    term: str          # e.g. '5y_fixed', 'variable_5y', 'prime'
    rate: float
    method: str        # 'row' or 'text'
    evidence: str


def _clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'template', 'svg']):
        tag.decompose()
    return soup


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


def _term_years(label: str) -> int | None:
    m = TERM.search(label)
    if not m:
        return None
    token = re.split(r'[- ]', m.group(0))[0].lower()
    token = re.sub(r'(?:years?|yrs?)$', '', token)
    years = int(token) if token.isdigit() else WORDS.get(token)
    return years if years in FIXED_TERMS else None


def _rates(text: str) -> list[float]:
    return [float(v) for v in PCT.findall(text) if MIN_RATE <= float(v) <= MAX_RATE]


def _posted_column(table: Tag | None) -> int | None:
    if table is None:
        return None
    header = table.find('tr')
    if header is None:
        return None
    cells = header.find_all(['th', 'td'])
    for i, cell in enumerate(cells):
        if re.search(r'\bposted\b', cell.get_text(' '), re.I):
            return i
    return None


def _rows(soup: BeautifulSoup) -> Iterable[tuple[str, list[str], int | None]]:
    for tr in soup.find_all('tr'):
        cells = [_norm(c.get_text(' ')) for c in tr.find_all(['td', 'th'])]
        if len(cells) >= 2:
            yield cells[0], cells[1:], _posted_column(tr.find_parent('table'))
    for block in soup.select('.card, li, .rate-card, .rate-row, dl'):
        heading = block.find(['h2', 'h3', 'h4', 'dt', 'strong'])
        if heading is None:
            continue
        label = _norm(heading.get_text(' '))
        rest = _norm(block.get_text(' '))[len(label):]
        yield label, [rest], None


def _row_rate(term: str, cells: list[str], posted_col: int | None) -> float | None:
    if posted_col is not None and 0 < posted_col <= len(cells):
        values = _rates(cells[posted_col - 1])
        if values:
            return values[0]
    joined = ' '.join(cells)
    values = _rates(joined)
    if not values:
        return None
    if term == 'variable_5y' and '=' in joined:
        return values[-1]
    if term == 'variable_5y':
        large = [v for v in values if v >= MIN_PRIME]
        return large[-1] if large else None
    return values[0]


def parse_rows(soup: BeautifulSoup) -> dict[str, ParsedRate]:
    out: dict[str, ParsedRate] = {}
    for label, cells, posted_col in _rows(soup):
        if SPECIAL.search(label):
            continue
        years = _term_years(label)
        if years is None:
            continue
        if VARIABLE.search(label):
            if years != 5:
                continue
            term = 'variable_5y'
        elif FIXED.search(label) or re.search(r'\byear\b', label, re.I):
            term = f'{years}y_fixed'
        else:
            continue
        if term in out:
            continue
        rate = _row_rate(term, cells, posted_col)
        if rate is not None:
            out[term] = ParsedRate(term, rate, 'row', _norm(label + ' ' + ' '.join(cells))[:200])
    return out


def parse_text(text: str, window: int = 80) -> dict[str, ParsedRate]:
    out: dict[str, ParsedRate] = {}
    for n in FIXED_TERMS:
        word = next(w for w, v in WORDS.items() if v == n)
        label = re.compile(
            rf'(?<![\d.])(?:{n}|{word})[- ]?(?:year|yr)s?\b[^%]{{0,40}}?\bfixed\b'
            rf'|\bfixed\b[^%]{{0,25}}?(?<![\d.])(?:{n}|{word})[- ]?(?:year|yr)s?\b(?!\s*variable)', re.I)
        for m in label.finditer(text):
            seg = text[m.end(): m.end() + window]
            values = _rates(seg)
            if values:
                out[f'{n}y_fixed'] = ParsedRate(f'{n}y_fixed', values[0], 'text', _norm(m.group(0) + seg)[:200])
                break
    return out


def parse_prime(text: str, label: str) -> ParsedRate | None:
    for m in re.finditer(label, text, re.I):
        seg = text[m.end(): m.end() + 60]
        values = [v for v in _rates(seg) if v >= MIN_PRIME]
        if values:
            return ParsedRate('prime', values[0], 'text', _norm(m.group(0) + seg)[:200])
    return None


def parse_page(html: str, prime_label: str = r'\bprime rate\b') -> dict[str, ParsedRate]:
    """All posted rates found on the page, keyed by term code."""
    soup = _clean_soup(html)
    text = _norm(soup.get_text(' '))
    rates = parse_text(text)
    rates.update(parse_rows(soup))     # structured rows win over loose text
    prime = parse_prime(text, prime_label)
    if prime is not None:
        rates['prime'] = prime
    return dict(sorted(rates.items()))
