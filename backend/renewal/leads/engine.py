"""Lead store: consent check, duplicate folding, scoring, encryption and withdrawal."""
from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .consent import ConsentRecord
from .identity import (Vault, duplicate_key, mask_email, mask_phone, normalize_email,
                       normalize_phone)
from .scoring import LeadFacts, score_lead
from .webhooks import Outbox

D = Decimal
DUPLICATE_WINDOW = timedelta(days=90)
PROVINCES = frozenset({'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'})


@dataclass(frozen=True)
class LeadInput:
    workspace_id: str
    name: str
    email: str | None
    phone: str | None
    province: str
    consent: ConsentRecord
    renewal_date: date | None = None
    balance: D | None = None
    current_rate: D | None = None
    market_rate: D | None = None
    has_statement: bool = False
    completed_analysis: bool = False


class LeadEngine:
    def __init__(self, filename: str | Path, vault: Vault, dedupe_secret: bytes,
                 outbox: Outbox | None = None, webhook_url: Callable[[str], str | None] = lambda wid: None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if len(dedupe_secret) < 16:
            raise ValueError('dedupe secret must be at least 16 bytes')
        self.filename = str(filename)
        self._vault = vault
        self._secret = dedupe_secret
        self._outbox = outbox
        self._webhook_url = webhook_url
        self._clock = clock
        self._lock = threading.Lock()
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, created TEXT NOT NULL,
                status TEXT NOT NULL, contact_sealed TEXT, province TEXT NOT NULL,
                renewal_date TEXT, balance_band TEXT, score INTEGER NOT NULL, band TEXT NOT NULL,
                score_parts TEXT NOT NULL, consent TEXT NOT NULL, withdraw_digest TEXT NOT NULL,
                submissions INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS lead_tenant ON leads(workspace_id, status, score);
            CREATE TABLE IF NOT EXISTS lead_keys (
                key TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id), created TEXT NOT NULL);
            ''')

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.filename, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def _band(balance: D | None) -> str | None:
        """Brokers see a band, not the exact balance, until they speak to the homeowner."""
        if balance is None:
            return None
        for top, label in ((D(250000), 'under_250k'), (D(500000), '250k_500k'),
                           (D(1000000), '500k_1m')):
            if balance < top:
                return label
        return '1m_plus'

    def submit(self, lead: LeadInput) -> dict:
        if lead.province not in PROVINCES:
            raise ValueError('unknown province code')
        if not lead.name.strip() or len(lead.name) > 120:
            raise ValueError('name is required, max 120 characters')
        email = normalize_email(lead.email) if lead.email else None
        phone = normalize_phone(lead.phone) if lead.phone else None
        if 'email' in lead.consent.contact_methods and not email:
            raise ValueError('email contact chosen but no email given')
        if 'phone' in lead.consent.contact_methods and not phone:
            raise ValueError('phone contact chosen but no phone given')
        keys = duplicate_key(self._secret, email=email, phone=phone, workspace_id=lead.workspace_id)
        now = self._clock()
        with self._lock, self._db() as db:
            placeholders = ','.join('?' * len(keys))
            existing = db.execute(
                f'SELECT l.id, l.created FROM lead_keys k JOIN leads l ON l.id = k.lead_id '  # nosec B608
                f'WHERE k.key IN ({placeholders}) AND l.status != ? ORDER BY l.created DESC LIMIT 1',
                (*keys, 'withdrawn')).fetchone()
            if existing and now - datetime.fromisoformat(existing['created']) < DUPLICATE_WINDOW:
                db.execute('UPDATE leads SET submissions = submissions + 1 WHERE id=?', (existing['id'],))
                return {'id': existing['id'], 'duplicate': True}
            score = score_lead(LeadFacts(lead.renewal_date, lead.balance, lead.current_rate, lead.market_rate,
                                         lead.has_statement, lead.completed_analysis), now.date())
            lead_id = str(uuid.uuid4())
            withdraw = secrets.token_urlsafe(24)
            contact = json.dumps({'name': lead.name.strip(), 'email': email, 'phone': phone})
            db.execute('INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                       (lead_id, lead.workspace_id, now.isoformat(), 'new', self._vault.seal(contact),
                        lead.province, lead.renewal_date and lead.renewal_date.isoformat(),
                        self._band(lead.balance), score.score, score.band, json.dumps(score.parts),
                        json.dumps(lead.consent.as_dict()), sha256(withdraw.encode()).hexdigest()))
            for key in keys:
                db.execute('INSERT OR REPLACE INTO lead_keys VALUES (?,?,?)', (key, lead_id, now.isoformat()))
        url = self._webhook_url(lead.workspace_id)
        if self._outbox is not None and url:
            self._outbox.enqueue(f'lead.created.{lead_id}', url, {
                'type': 'lead.created', 'lead_id': lead_id, 'score': score.score, 'band': score.band,
                'province': lead.province, 'renewal_date': lead.renewal_date and lead.renewal_date.isoformat(),
                'balance_band': self._band(lead.balance)})
        return {'id': lead_id, 'duplicate': False, 'score': score.score, 'band': score.band,
                'withdraw_token': withdraw}

    def withdraw(self, lead_id: str, token: str) -> None:
        """Homeowner withdrawal: contact details erased, keys dropped, tombstone kept."""
        with self._lock, self._db() as db:
            row = db.execute('SELECT withdraw_digest, workspace_id FROM leads WHERE id=? AND status != ?',
                             (lead_id, 'withdrawn')).fetchone()
            if row is None or not hmac.compare_digest(row['withdraw_digest'], sha256(token.encode()).hexdigest()):
                raise PermissionError('lead not found')
            db.execute("UPDATE leads SET status='withdrawn', contact_sealed=NULL WHERE id=?", (lead_id,))
            db.execute('DELETE FROM lead_keys WHERE lead_id=?', (lead_id,))
            workspace = row['workspace_id']
        url = self._webhook_url(workspace)
        if self._outbox is not None and url:
            self._outbox.enqueue(f'lead.withdrawn.{lead_id}', url, {'type': 'lead.withdrawn', 'lead_id': lead_id})

    def for_broker(self, workspace_id: str, *, reveal: bool = False, status: str | None = None) -> list[dict]:
        """Leads for one brokerage, highest score first. Contacts are masked unless ``reveal``."""
        query = 'SELECT * FROM leads WHERE workspace_id=?'
        params: list = [workspace_id]
        if status:
            query += ' AND status=?'
            params.append(status)
        with self._db() as db:
            rows = db.execute(query + ' ORDER BY score DESC, created', params).fetchall()
        out = []
        for r in rows:
            item = {'id': r['id'], 'created': r['created'], 'status': r['status'], 'province': r['province'],
                    'renewal_date': r['renewal_date'], 'balance_band': r['balance_band'], 'score': r['score'],
                    'band': r['band'], 'score_parts': json.loads(r['score_parts']),
                    'submissions': r['submissions'], 'consent': json.loads(r['consent'])}
            if r['contact_sealed']:
                c = json.loads(self._vault.open(r['contact_sealed']))
                item['contact'] = c if reveal else {
                    'name': c['name'].split(' ')[0], 'email': c['email'] and mask_email(c['email']),
                    'phone': c['phone'] and mask_phone(c['phone'])}
            out.append(item)
        return out

    def reveal(self, workspace_id: str, lead_id: str) -> dict:
        """Full contact for one lead of this brokerage; callers must audit the access."""
        with self._db() as db:
            row = db.execute("SELECT contact_sealed FROM leads WHERE id=? AND workspace_id=? "
                             "AND status != 'withdrawn'", (lead_id, workspace_id)).fetchone()
        if row is None or not row['contact_sealed']:
            raise PermissionError('lead not found')
        return json.loads(self._vault.open(row['contact_sealed']))

    def set_status(self, workspace_id: str, lead_id: str, status: str) -> None:
        if status not in ('contacted', 'qualified', 'closed'):
            raise ValueError('status must be contacted, qualified or closed')
        with self._lock, self._db() as db:
            cur = db.execute("UPDATE leads SET status=? WHERE id=? AND workspace_id=? AND status != 'withdrawn'",
                             (status, lead_id, workspace_id))
            if cur.rowcount != 1:
                raise PermissionError('lead not found')
