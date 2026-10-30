"""Time-versioned, source-backed mortgage rate observations.

Observations represent what a named public source reported *at collection time*.
They are never automatically characterized as offers to a specific borrower.
The service requires both a publication URL and a capture timestamp, records
content hashes, preserves revisions, and refuses to infer historical rates.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse
import json
import re
import sqlite3

RATE_TYPES = frozenset({'fixed', 'variable'})
RATE_KINDS = frozenset({'posted', 'special', 'benchmark', 'contract'})
_MAX_RATE = Decimal('30')
_LOCK = RLock()


def utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamp must include an explicit UTC offset')
    return value.astimezone(timezone.utc)


def validate_source(url: str) -> str:
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('An HTTPS public source URL without credentials is required')
    if p.hostname in ('localhost', '127.0.0.1', '0.0.0.0') or p.hostname.endswith('.local'):
        raise ValueError('Local network addresses are not valid publication sources')
    return url


@dataclass(frozen=True)
class RateObservation:
    lender: str
    product: str
    rate_type: str
    term_months: int
    annual_rate: str
    rate_kind: str
    effective_at: str
    captured_at: str
    source_url: str
    source_sha256: str
    evidence: str
    provenance: str = 'official_lender_page'
    currency: str = 'CAD'

    def validate(self) -> None:
        if not self.lender.strip() or len(self.lender) > 100:
            raise ValueError('Lender must be 1–100 characters')
        if not self.product.strip() or len(self.product) > 200:
            raise ValueError('Product must be 1–200 characters')
        if self.rate_type not in RATE_TYPES or self.rate_kind not in RATE_KINDS:
            raise ValueError('Unknown rate type or rate kind')
        if type(self.term_months) is not int or not 1 <= self.term_months <= 480:
            raise ValueError('Term must be 1 to 480 months')
        try:
            rate = Decimal(self.annual_rate)
        except InvalidOperation as e:
            raise ValueError('Annual rate is not decimal') from e
        if not rate.is_finite() or not 0 <= rate <= _MAX_RATE:
            raise ValueError('Annual rate outside plausible bounds')
        observed = utc(self.effective_at)
        captured = utc(self.captured_at)
        if captured > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Capture timestamp cannot be in the future')
        if observed > captured + timedelta(days=1):
            raise ValueError('Effective timestamp cannot be after capture')
        validate_source(self.source_url)
        if not re.fullmatch(r'[0-9a-f]{64}', self.source_sha256):
            raise ValueError('SHA-256 hash must be lowercase hex')
        if not self.evidence.strip() or len(self.evidence) > 500:
            raise ValueError('A short evidence excerpt is mandatory')
        if self.currency != 'CAD':
            raise ValueError('Only Canadian-dollar mortgage observations supported')

    @property
    def canonical_id(self) -> str:
        payload = '|'.join([self.lender.lower().strip(), self.product.lower().strip(),
                            self.rate_type, str(self.term_months), self.annual_rate,
                            self.rate_kind, utc(self.effective_at).isoformat(),
                            self.source_url, self.source_sha256])
        return sha256(payload.encode()).hexdigest()


class RateArchive:
    """SQLite-backed append-only source archive with duplicate idempotency.

    A changed source snapshot becomes a new observation, never an update to the
    original rate. A correction is independently recorded with superseded_id.
    """

    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.filename, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    def _initialize(self):
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS rate_observations (
                    id TEXT PRIMARY KEY,
                    lender TEXT NOT NULL,
                    product TEXT NOT NULL,
                    rate_type TEXT NOT NULL,
                    term_months INTEGER NOT NULL,
                    annual_rate TEXT NOT NULL,
                    rate_kind TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    superseded_id TEXT,
                    FOREIGN KEY(superseded_id) REFERENCES rate_observations(id)
                );
                CREATE INDEX IF NOT EXISTS rates_lookup ON rate_observations
                    (lender,rate_type,term_months,rate_kind,effective_at,captured_at);
                CREATE INDEX IF NOT EXISTS rates_snapshot ON rate_observations
                    (source_sha256,captured_at);
            ''')

    def append(self, observation: RateObservation, superseded_id: str | None = None) -> dict:
        observation.validate()
        entry = {**asdict(observation), 'id': observation.canonical_id,
                 'effective_at': utc(observation.effective_at).isoformat(),
                 'captured_at': utc(observation.captured_at).isoformat(),
                 'superseded_id': superseded_id}
        with _LOCK, self._connect() as db:
            if superseded_id and not db.execute('SELECT 1 FROM rate_observations WHERE id=?',
                                                 (superseded_id,)).fetchone():
                raise ValueError('Cannot supersede a nonexistent observation')
            db.execute('''INSERT OR IGNORE INTO rate_observations
                (id,lender,product,rate_type,term_months,annual_rate,rate_kind,
                 effective_at,captured_at,source_url,source_sha256,evidence,
                 provenance,currency,superseded_id)
                VALUES (:id,:lender,:product,:rate_type,:term_months,:annual_rate,
                        :rate_kind,:effective_at,:captured_at,:source_url,
                        :source_sha256,:evidence,:provenance,:currency,:superseded_id)''', entry)
            db.commit()
        return entry

    def history(self, lender: str, *, term_months: int | None = None,
                rate_type: str | None = None, rate_kind: str | None = None,
                as_of: str | None = None, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError('Limit must be between 1 and 500')
        conditions = ['LOWER(lender)=LOWER(?)']
        parameters: list = [lender]
        for column, value in [('term_months', term_months), ('rate_type', rate_type),
                              ('rate_kind', rate_kind)]:
            if value is not None:
                conditions.append(f'{column}=?')
                parameters.append(value)
        if as_of is not None:
            conditions.append('captured_at<=?')
            parameters.append(utc(as_of).isoformat())
        parameters.append(limit)
        query = 'SELECT * FROM rate_observations WHERE ' + ' AND '.join(conditions) + \
                ' ORDER BY effective_at DESC,captured_at DESC,id LIMIT ?'
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, parameters)]

    def reconstruct_discount(self, lender: str, original_effective_date: str,
                             original_contract_rate: str, term_months: int,
                             *, rate_type: str = 'fixed', max_age_days: int = 7) -> dict:
        """Retrieve evidence near origination; never invent an absent historical rate.

        A dated posted rate is useful evidence, but may differ from contractual
        rate sheets or lender-specific prepayment provisions.
        """
        at = utc(original_effective_date)
        history = self.history(lender, term_months=term_months, rate_type=rate_type,
                               rate_kind='posted', limit=500)
        eligible = [r for r in history if utc(r['effective_at']) <= at and
                    0 <= (at - utc(r['effective_at'])).days <= max_age_days and
                    utc(r['captured_at']) <= datetime.now(timezone.utc)]
        if not eligible:
            return {'status': 'insufficient_evidence', 'discount_pp': None,
                    'message': 'No dated lender posted-rate observation within the allowed window.'}
        chosen = max(eligible, key=lambda r: (r['effective_at'], r['captured_at']))
        difference = Decimal(chosen['annual_rate']) - Decimal(original_contract_rate)
        return {'status': 'estimated_historical_discount', 'discount_pp': str(difference),
                'source_id': chosen['id'], 'source_url': chosen['source_url'],
                'effective_at': chosen['effective_at'],
                'warning': 'A rate-page observation cannot establish the discount printed in a signed contract.'}


def source_hash(raw: bytes) -> str:
    return sha256(raw).hexdigest()
