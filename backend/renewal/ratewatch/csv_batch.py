"""Strict Ratewatch CSV batch validation (RateRow) and whole-batch quarantine rules.

Canonical headers (exact, utf-8-sig)::

    date,lender,term_months,rate_pct,rate_type

Rates are Decimal in [0, 25]. Terms must be in the closed-mortgage allowlist.
Any single bad row quarantines the entire batch. Sanity checks vs last-good
(row-count swing, rate jumps, missing lenders) also quarantine.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable

# Exact header order and names (BOM stripped via utf-8-sig).
HEADERS: tuple[str, ...] = ('date', 'lender', 'term_months', 'rate_pct', 'rate_type')
ALLOWED_TERMS: frozenset[int] = frozenset({6, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120})
ALLOWED_RATE_TYPES: frozenset[str] = frozenset({'posted', 'special'})
RATE_MIN = Decimal('0')
RATE_MAX = Decimal('25')
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5_000
MAX_LENDER_LEN = 80

# Sanity vs last-good (whole-batch quarantine thresholds).
ROW_SWING_RATIO = Decimal('0.50')   # |new-old|/old > 50% when old >= MIN_ROWS_FOR_SWING
MIN_ROWS_FOR_SWING = 5
RATE_JUMP_PP = Decimal('2.0')      # same lender+term absolute jump


class BatchValidationError(ValueError):
    """One or more structural/schema failures; batch must be quarantined."""


@dataclass(frozen=True)
class RateRow:
    observed: date
    lender: str
    term_months: int
    rate_pct: Decimal
    rate_type: str

    @property
    def dup_key(self) -> tuple:
        return (self.observed.isoformat(), self.lender, self.term_months, self.rate_type)

    def as_dict(self) -> dict[str, str]:
        return {
            'date': self.observed.isoformat(),
            'lender': self.lender,
            'term_months': str(self.term_months),
            'rate_pct': format(self.rate_pct, 'f'),
            'rate_type': self.rate_type,
        }


@dataclass
class ParseResult:
    rows: list[RateRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sha256: str = ''
    byte_size: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.rows)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_rate(raw: str) -> Decimal:
    text = (raw or '').strip().replace('%', '')
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f'invalid rate_pct {raw!r}') from exc
    if not RATE_MIN <= value <= RATE_MAX:
        raise ValueError(f'rate_pct {value} outside 0..25')
    # Reject non-finite / weird exponents by requiring finite and reasonable precision
    if not value.is_finite():
        raise ValueError('rate_pct must be finite')
    return value


def parse_rate_csv(data: bytes) -> ParseResult:
    """Parse and strictly validate a Ratewatch batch CSV. Never partial-accept."""
    result = ParseResult(byte_size=len(data), sha256=_sha256(data))
    if len(data) > MAX_BYTES:
        result.errors.append(f'CSV exceeds {MAX_BYTES // (1024 * 1024)} MB size cap')
        return result
    if not data:
        result.errors.append('CSV is empty')
        return result
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        result.errors.append(f'CSV must be utf-8-sig: {exc}')
        return result

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        result.errors.append('CSV has no header row')
        return result
    header = [h.strip() for h in header]
    if tuple(header) != HEADERS:
        result.errors.append(
            f'exact headers required: {",".join(HEADERS)}; got: {",".join(header)}'
        )
        return result

    seen: set[tuple] = set()
    for lineno, cells in enumerate(reader, start=2):
        if not cells or all(not (c or '').strip() for c in cells):
            continue
        if len(result.rows) >= MAX_ROWS:
            result.errors.append(f'CSV exceeds {MAX_ROWS} data rows')
            break
        if len(cells) != len(HEADERS):
            result.errors.append(f'line {lineno}: expected {len(HEADERS)} columns, got {len(cells)}')
            continue
        row_map = dict(zip(HEADERS, (c.strip() for c in cells)))
        try:
            observed = date.fromisoformat(row_map['date'])
            if not date(1990, 1, 1) <= observed <= date.today():
                raise ValueError(f'date {observed} out of range')
            lender = row_map['lender'].strip()
            if not lender or len(lender) > MAX_LENDER_LEN:
                raise ValueError('lender missing or too long')
            term = int(row_map['term_months'])
            if term not in ALLOWED_TERMS:
                raise ValueError(f'term_months {term} not in allowlist')
            rate = _parse_rate(row_map['rate_pct'])
            rate_type = row_map['rate_type'].strip().lower()
            if rate_type not in ALLOWED_RATE_TYPES:
                raise ValueError(f'rate_type {rate_type!r} not allowed')
            row = RateRow(observed, lender, term, rate, rate_type)
            if row.dup_key in seen:
                raise ValueError(f'duplicate row {row.dup_key}')
            seen.add(row.dup_key)
            result.rows.append(row)
        except ValueError as exc:
            result.errors.append(f'line {lineno}: {exc}')

    if not result.rows and not result.errors:
        result.errors.append('CSV has no data rows')
    return result


def sanity_vs_last_good(
    new_rows: Iterable[RateRow],
    last_rows: Iterable[RateRow] | None,
) -> list[str]:
    """Return quarantine reasons if the new batch fails vs last-good. Empty = OK."""
    reasons: list[str] = []
    new_list = list(new_rows)
    if last_rows is None:
        return reasons
    old_list = list(last_rows)
    if not old_list:
        return reasons

    n_new, n_old = len(new_list), len(old_list)
    if n_old >= MIN_ROWS_FOR_SWING:
        swing = abs(Decimal(n_new) - Decimal(n_old)) / Decimal(n_old)
        if swing > ROW_SWING_RATIO:
            reasons.append(
                f'row count swing {float(swing):.0%} (new={n_new}, last_good={n_old})'
            )

    old_lenders = {r.lender for r in old_list}
    new_lenders = {r.lender for r in new_list}
    missing = sorted(old_lenders - new_lenders)
    if missing:
        reasons.append(f'missing lender(s) vs last-good: {", ".join(missing[:20])}')

    # Latest rate per (lender, term) in each batch (by date).
    def latest_map(rows: list[RateRow]) -> dict[tuple[str, int], RateRow]:
        best: dict[tuple[str, int], RateRow] = {}
        for r in rows:
            key = (r.lender, r.term_months)
            prev = best.get(key)
            if prev is None or r.observed > prev.observed or (
                r.observed == prev.observed and r.rate_type == 'posted'
            ):
                best[key] = r
        return best

    old_map = latest_map(old_list)
    new_map = latest_map(new_list)
    for key, old_row in old_map.items():
        new_row = new_map.get(key)
        if new_row is None:
            continue
        jump = abs(new_row.rate_pct - old_row.rate_pct)
        if jump > RATE_JUMP_PP:
            reasons.append(
                f'rate jump {jump} pp for {key[0]} {key[1]}m '
                f'({old_row.rate_pct} -> {new_row.rate_pct})'
            )
    return reasons


def rows_to_csv_bytes(rows: Iterable[RateRow]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(HEADERS), lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_dict())
    return buf.getvalue().encode('utf-8')
