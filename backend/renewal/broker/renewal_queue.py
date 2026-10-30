"""Tenant-separated renewal outreach queue with explicit consent checks.

No jobs contact clients. This service returns due tasks only. A delivery integration
must re-check consent immediately before sending and record a completed action.
All dates are ISO calendar dates, not machine-local timestamps.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

WINDOWS = (180, 120, 90, 60, 30, 14, 7, 0)
STATES = frozenset({'open', 'completed', 'dismissed'})
_LOCK = RLock()


def _today() -> str:
    return date.today().isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('Expected a YYYY-MM-DD calendar date') from exc


@dataclass(frozen=True)
class RenewalSignal:
    client_id: str
    renewal_date: str
    days_remaining: int
    threshold_days: int
    priority: str
    requires_consent: bool
    recommended_action: str

    def dict(self) -> dict:
        return self.__dict__.copy()


def threshold_for(days: int) -> int | None:
    """Identify the nearest milestone already reached without future leakage."""
    if days < 0:
        return 0
    return next((window for window in reversed(WINDOWS) if days <= window), None)


def assess_renewal(client_id: str, renewal_date: str, as_of: str,
                   consent: bool) -> RenewalSignal | None:
    due = _as_date(renewal_date)
    current = _as_date(as_of)
    days = (due - current).days
    threshold = threshold_for(days)
    if threshold is None:
        return None
    if days < 0:
        priority = 'overdue'
        action = 'Confirm renewal outcome and whether the mortgage has matured.'
    elif days <= 14:
        priority = 'critical'
        action = 'Verify signed renewal, closing dates, payout statement and contingency.'
    elif days <= 60:
        priority = 'high'
        action = 'Compare committed offers, switching eligibility and total transaction costs.'
    elif days <= 120:
        priority = 'medium'
        action = 'Request renewal quote and verify documents with the homeowner.'
    else:
        priority = 'early'
        action = 'Begin renewal planning and review prepayment restrictions.'
    return RenewalSignal(client_id, renewal_date, days, threshold, priority,
                         not consent, action)


class RenewalQueue:
    """Durable task state and tamper-evident changes scoped by workspace.

    External tenant authentication is intentionally handled by BrokerWorkspace;
    this class never accepts an unvalidated workspace id from a public caller.
    """

    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS renewal_tasks (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                client_id TEXT NOT NULL, milestone INTEGER NOT NULL,
                maturity_date TEXT NOT NULL, priority TEXT NOT NULL,
                action TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, updated TEXT NOT NULL,
                UNIQUE(workspace_id, client_id, milestone, maturity_date));
            CREATE INDEX IF NOT EXISTS renewal_task_scope
                ON renewal_tasks(workspace_id, state, maturity_date);
            CREATE TABLE IF NOT EXISTS renewal_task_events (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL, transition TEXT NOT NULL,
                previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL, note TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS renewal_event_scope
                ON renewal_task_events(workspace_id,task_id,timestamp);
            ''')

    def _db(self):
        conn = sqlite3.connect(self.filename, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _task(row) -> dict:
        return dict(row)

    def _event(self, db, workspace_id: str, task_id: str, transition: str,
               note: str = '') -> None:
        previous = db.execute('''SELECT event_hash FROM renewal_task_events
            WHERE task_id=? AND workspace_id=? ORDER BY timestamp DESC,id DESC LIMIT 1''',
            (task_id, workspace_id)).fetchone()
        prior = previous['event_hash'] if previous else 'GENESIS'
        stamp = _timestamp()
        payload = json.dumps([prior, workspace_id, task_id, transition, stamp, note],
                             ensure_ascii=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        db.execute('''INSERT INTO renewal_task_events VALUES (?,?,?,?,?,?,?,?)''',
                   (str(uuid.uuid4()), task_id, workspace_id, transition,
                    prior, digest, stamp, note))

    def synchronize(self, workspace_id: str, records: list[dict],
                    as_of: str | None = None) -> dict:
        """Create due tasks idempotently; never automatically contact a client."""
        current = as_of or _today()
        _as_date(current)
        if len(records) > 10000:
            raise ValueError('Import exceeds the 10,000-record safety limit')
        signals = []
        errors = []
        for index, record in enumerate(records):
            try:
                if not record.get('client_id') or not isinstance(record['client_id'], str):
                    raise ValueError('Client id required')
                maturity = record.get('renewal_date')
                if not maturity:
                    continue
                signal = assess_renewal(record['client_id'], maturity, current,
                                        record.get('contact_consent') is True)
                if signal:
                    signals.append(signal)
            except (ValueError, TypeError) as exc:
                errors.append({'row': index + 1, 'error': str(exc)})
        inserted = 0
        with _LOCK, self._db() as db:
            for signal in signals:
                # Outstanding tasks can be viewed even without contact consent.
                # Such tasks are marked with a consent warning in the API.
                stamp = _timestamp()
                task_id = str(uuid.uuid4())
                cursor = db.execute('''INSERT OR IGNORE INTO renewal_tasks
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (task_id, workspace_id, signal.client_id,
                     signal.threshold_days, signal.renewal_date, signal.priority,
                     signal.recommended_action, 'open', stamp, stamp))
                if cursor.rowcount:
                    inserted += 1
                    self._event(db, workspace_id, task_id, 'created',
                                'Explicit consent required before contact')
        return {'considered': len(records), 'eligible': len(signals),
                'inserted': inserted, 'skipped_or_existing': len(signals)-inserted,
                'errors': errors, 'notifications_sent': 0}

    def list_tasks(self, workspace_id: str, state: str | None = 'open',
                   limit: int = 100) -> list[dict]:
        if state is not None and state not in STATES:
            raise ValueError('Invalid task state')
        if not 1 <= limit <= 1000:
            raise ValueError('Limit must be from 1 through 1,000')
        sql = 'SELECT * FROM renewal_tasks WHERE workspace_id=?'
        params: list = [workspace_id]
        if state is not None:
            sql += ' AND state=?'
            params.append(state)
        sql += ' ORDER BY maturity_date,created,id LIMIT ?'
        params.append(limit)
        with self._db() as db:
            return [self._task(row) for row in db.execute(sql, params)]

    def change_state(self, workspace_id: str, task_id: str, new_state: str,
                     note: str = '') -> dict | None:
        if new_state not in STATES:
            raise ValueError('Invalid task state')
        if len(note) > 1000:
            raise ValueError('Note must be 1,000 characters or less')
        with _LOCK, self._db() as db:
            row = db.execute('SELECT * FROM renewal_tasks WHERE id=? AND workspace_id=?',
                             (task_id, workspace_id)).fetchone()
            if row is None:
                return None
            old_state = row['state']
            if old_state == new_state:
                return self._task(row)
            db.execute('UPDATE renewal_tasks SET state=?,updated=? WHERE id=? AND workspace_id=?',
                       (new_state, _timestamp(), task_id, workspace_id))
            self._event(db, workspace_id, task_id, f'{old_state}->{new_state}', note)
            updated = db.execute('SELECT * FROM renewal_tasks WHERE id=?', (task_id,)).fetchone()
            return self._task(updated)

    def events(self, workspace_id: str, task_id: str) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute('''SELECT * FROM renewal_task_events
                 WHERE workspace_id=? AND task_id=? ORDER BY timestamp,id''',
                 (workspace_id, task_id))]
