"""Broker tenant boundaries, client authorization, and consent audit records.

For the pre-production demo, opaque workspace tokens are used instead of a
third-party identity provider. The token is hashed before storage; a bearer
credential must be supplied for every broker operation. No bank credentials
or PDF contents are stored. This is not a substitute for production auth.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

_LOCK = RLock()
SCOPES = frozenset({'view_case', 'request_documents', 'share_report',
                    'contact_homeowner', 'bank_data_read'})

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

class AccessDenied(Exception):
    pass

class BrokerWorkspace:
    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS broker_workspaces (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, token_digest TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broker_clients (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, alias TEXT NOT NULL,
                renewal_date TEXT, created TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES broker_workspaces(id));
            CREATE INDEX IF NOT EXISTS client_tenant ON broker_clients(workspace_id);
            CREATE TABLE IF NOT EXISTS broker_consents (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, client_id TEXT NOT NULL,
                scope TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL,
                recorded TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES broker_clients(id));
            CREATE INDEX IF NOT EXISTS consent_tenant ON broker_consents(workspace_id,client_id,scope);
            CREATE TABLE IF NOT EXISTS broker_events (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, client_id TEXT,
                actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, timestamp TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_tenant ON broker_events(workspace_id,timestamp);
            ''')

    def _db(self):
        db = sqlite3.connect(self.filename, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def create_workspace(self, name: str) -> dict:
        if not name.strip() or len(name) > 120:
            raise ValueError('Workspace name is required and must be under 120 characters')
        wid = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        with _LOCK, self._db() as db:
            db.execute('INSERT INTO broker_workspaces VALUES (?,?,?,?)',
                       (wid, name.strip(), secret_hash(token), now()))
        return {'workspace_id': wid, 'access_token': token, 'name': name.strip(),
                'warning': 'Store your workspace token securely; it cannot be recovered.'}

    def _assert_access(self, wid: str, token: str):
        with self._db() as db:
            row = db.execute('SELECT token_digest FROM broker_workspaces WHERE id=?', (wid,)).fetchone()
        if not row or not hmac.compare_digest(row['token_digest'], secret_hash(token or '')):
            raise AccessDenied('Invalid broker credentials')

    def _audit(self, db, wid: str, cid: str | None, action: str, detail: dict):
        db.execute('INSERT INTO broker_events VALUES (?,?,?,?,?,?,?)',
                   (str(uuid.uuid4()), wid, cid, 'broker_workspace', action,
                    json.dumps(detail, sort_keys=True), now()))

    def add_client(self, wid: str, token: str, alias: str, renewal_date: str | None = None) -> dict:
        self._assert_access(wid, token)
        if not alias.strip() or len(alias) > 120:
            raise ValueError('Client alias required, max 120 chars')
        if renewal_date is not None:
            from datetime import date
            date.fromisoformat(renewal_date)
        cid = str(uuid.uuid4())
        with _LOCK, self._db() as db:
            db.execute('INSERT INTO broker_clients VALUES (?,?,?,?,?)',
                       (cid, wid, alias.strip(), renewal_date, now()))
            self._audit(db, wid, cid, 'client_added', {'renewal_date': renewal_date})
        return {'id': cid, 'alias': alias.strip(), 'renewal_date': renewal_date}

    def clients(self, wid: str, token: str) -> list[dict]:
        self._assert_access(wid, token)
        with self._db() as db:
            return [dict(r) for r in db.execute(
                'SELECT id,alias,renewal_date,created FROM broker_clients '
                'WHERE workspace_id=? ORDER BY renewal_date IS NULL,renewal_date,created', (wid,))]

    def record_consent(self, wid: str, token: str, cid: str, scope: str,
                       status: str, evidence: str) -> dict:
        self._assert_access(wid, token)
        if scope not in SCOPES:
            raise ValueError('Unknown consent scope')
        if status not in ('granted', 'revoked'):
            raise ValueError('Consent status must be granted or revoked')
        if not evidence.strip() or len(evidence) > 500:
            raise ValueError('Consent requires bounded evidence describing how it was obtained')
        item = {'id': str(uuid.uuid4()), 'workspace_id': wid, 'client_id': cid,
                'scope': scope, 'status': status, 'evidence': evidence.strip(), 'recorded': now()}
        with _LOCK, self._db() as db:
            found = db.execute('SELECT 1 FROM broker_clients WHERE workspace_id=? AND id=?',
                               (wid, cid)).fetchone()
            if not found:
                raise AccessDenied('Client not found in this workspace')
            db.execute('INSERT INTO broker_consents VALUES (:id,:workspace_id,:client_id,'
                       ':scope,:status,:evidence,:recorded)', item)
            self._audit(db, wid, cid, 'consent_'+status, {'scope': scope, 'consent_id': item['id']})
        return item

    def has_consent(self, wid: str, token: str, cid: str, scope: str) -> bool:
        self._assert_access(wid, token)
        with self._db() as db:
            row = db.execute('SELECT status FROM broker_consents WHERE workspace_id=? '
                             'AND client_id=? AND scope=? ORDER BY recorded DESC,rowid DESC LIMIT 1',
                             (wid, cid, scope)).fetchone()
        return bool(row and row['status'] == 'granted')

    def audit(self, wid: str, token: str, limit: int = 100) -> list[dict]:
        self._assert_access(wid, token)
        if not 1 <= limit <= 500:
            raise ValueError('Invalid audit result limit')
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT id,client_id,action,detail,timestamp '
                'FROM broker_events WHERE workspace_id=? ORDER BY timestamp DESC,rowid DESC LIMIT ?',
                (wid, limit))]
