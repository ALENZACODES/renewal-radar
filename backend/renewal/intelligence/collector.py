"""Controlled official-source rate collection with an auditable quarantine.

Collection never equates a public posted rate with a borrower-specific offer.
Historical backfilling requires an authenticated archived source, not a guess.
The HTTP transport is injected to allow fully offline tests. External redirects,
embedded credentials and unknown domains fail closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
import asyncio
import json
import sqlite3

import httpx

from .rate_history import RateArchive, RateObservation, validate_source
from ..providers.bank_rates import parse_official_posted_html
from ..services.market import BANK_SOURCES

MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class OfficialSource:
    lender: str
    url: str
    product: str = 'Five-year fixed posted mortgage'
    term_months: int = 60

    def check(self) -> None:
        validate_source(self.url)
        if self.term_months != 60:
            raise ValueError('This collector only validates five-year fixed posted rates')
        if not self.lender or len(self.lender) > 100:
            raise ValueError('Invalid lender')


def official_sources() -> list[OfficialSource]:
    return [OfficialSource(name, url) for name, url in BANK_SOURCES]


class CollectionJournal:
    """Records every attempt, even when HTML is ambiguous or inaccessible."""

    def __init__(self, database: str | Path):
        self.database = str(database)
        with self._db() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS collection_events (
                id TEXT PRIMARY KEY, lender TEXT NOT NULL, source_url TEXT NOT NULL,
                captured_at TEXT NOT NULL, status TEXT NOT NULL,
                page_sha256 TEXT, http_status INTEGER, evidence TEXT,
                observation_id TEXT, detail TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS collection_lender_date ON collection_events(lender,captured_at)')

    def _db(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        return db

    def record(self, event: dict) -> dict:
        allowed = {'lender', 'source_url', 'captured_at', 'status', 'page_sha256',
                   'http_status', 'evidence', 'observation_id', 'detail'}
        record = {name: event.get(name) for name in allowed}
        record['id'] = sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        with self._db() as conn:
            conn.execute('''INSERT OR IGNORE INTO collection_events
                (id,lender,source_url,captured_at,status,page_sha256,http_status,
                 evidence,observation_id,detail)
                 VALUES (:id,:lender,:source_url,:captured_at,:status,:page_sha256,
                         :http_status,:evidence,:observation_id,:detail)''', record)
        return record

    def recent(self, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError('Limit outside 1-500')
        with self._db() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM collection_events ORDER BY captured_at DESC,id DESC LIMIT ?', (limit,))]


class RateCollector:
    def __init__(self, archive: RateArchive, journal: CollectionJournal,
                 sources: list[OfficialSource] | None = None):
        self.archive = archive
        self.journal = journal
        self.sources = sources if sources is not None else official_sources()
        for source in self.sources:
            source.check()
        # Network policy: only configured source hosts, never discovered links.
        self.allowed_hosts = {urlsplit(source.url).hostname for source in self.sources}

    async def collect_one(self, source: OfficialSource, client: httpx.AsyncClient,
                          *, now: datetime | None = None) -> dict:
        source.check()
        if source not in self.sources:
            raise ValueError('Source not explicitly registered for collection')
        captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        event = dict(lender=source.lender, source_url=source.url, captured_at=captured,
                     status='unverified', page_sha256=None, http_status=None,
                     evidence=None, observation_id=None, detail='No published rate verified')
        try:
            # follow_redirects=False: a lender redirect is not automatically trusted.
            resp = await client.get(source.url, follow_redirects=False,
                                    headers={'Accept': 'text/html'})
            event['http_status'] = resp.status_code
            if resp.status_code in (301, 302, 303, 307, 308):
                event.update(status='redirect_quarantined', detail='Redirect requires source URL review')
                return self.journal.record(event)
            resp.raise_for_status()
            if len(resp.content) > MAX_RESPONSE_BYTES:
                event.update(status='oversize_quarantined', detail='HTML body exceeded configured limit')
                return self.journal.record(event)
            mimetype = resp.headers.get('content-type', '').split(';')[0].strip().lower()
            if mimetype not in ('text/html', 'application/xhtml+xml'):
                event.update(status='content_type_quarantined', detail='Expected HTML document')
                return self.journal.record(event)
            event['page_sha256'] = sha256(resp.content).hexdigest()
            parsed = parse_official_posted_html(resp.text)
            if parsed.get('value') is None:
                event.update(status='ambiguous_quarantined', detail=parsed.get('reason', 'Cannot verify rate'))
                return self.journal.record(event)
            value = Decimal(str(parsed['value']))
            evidence = parsed['evidence']
            observation = RateObservation(
                lender=source.lender, product=source.product, rate_type='fixed',
                term_months=source.term_months, annual_rate=str(value), rate_kind='posted',
                effective_at=captured, captured_at=captured, source_url=source.url,
                source_sha256=event['page_sha256'], evidence=evidence,
                provenance='official_lender_page_auto_collected')
            item = self.archive.append(observation)
            event.update(status='verified_public_posted', evidence=evidence,
                         observation_id=item['id'], detail='Unambiguous 5-year fixed posted row')
        except (httpx.HTTPError, UnicodeError) as exc:
            event.update(status='fetch_error', detail=f'{type(exc).__name__}: source fetch failed')
        return self.journal.record(event)

    async def run(self, client: httpx.AsyncClient, *, parallel: int = 3) -> dict:
        if parallel < 1 or parallel > 8:
            raise ValueError('Concurrency must be between 1 and 8')
        limiter = asyncio.Semaphore(parallel)

        async def run_source(source: OfficialSource):
            async with limiter:
                return await self.collect_one(source, client)

        events = await asyncio.gather(*(run_source(s) for s in self.sources))
        return {'attempted': len(events),
                'verified': sum(e['status'] == 'verified_public_posted' for e in events),
                'quarantined_or_failed': sum(e['status'] != 'verified_public_posted' for e in events),
                'events': events,
                'note': 'Public posted rate snapshots are not personal rate offers or reconstructed historical rates.'}
