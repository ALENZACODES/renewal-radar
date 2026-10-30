"""Tenant-scoped broker dashboard on top of ``BrokerWorkspace``.

Adds client profiles (stage, balance, rate, lender), stage history, follow-up
tasks and a dashboard summary. Every call re-checks the workspace token; every
query is filtered by workspace id so one broker can never read another's clients.
"""
from __future__ import annotations

import sqlite3
import uuid
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Callable

from .pipeline import (CLOSED, ClientFacts, Stage, Window, check_transition, priority, window)
from .workspace import _LOCK, AccessDenied, BrokerWorkspace, now

D = Decimal
MarketRate = Callable[[str | None, date], D | None]
CONTACT_TASK_KINDS = frozenset({'call', 'email', 'meeting'})


class BrokerDashboard:
    def __init__(self, workspace: BrokerWorkspace, market_rate: MarketRate | None = None,
                 today: Callable[[], date] = date.today) -> None:
        self.ws = workspace
        self._market = market_rate or (lambda lender, day: None)
        self._today = today
        with self.ws._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS broker_profiles (
                client_id TEXT PRIMARY KEY REFERENCES broker_clients(id),
                workspace_id TEXT NOT NULL, stage TEXT NOT NULL,
                lender TEXT, balance TEXT, rate_pct TEXT, rate_type TEXT, updated TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS profile_tenant ON broker_profiles(workspace_id, stage);
            CREATE TABLE IF NOT EXISTS broker_stage_history (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, client_id TEXT NOT NULL,
                from_stage TEXT, to_stage TEXT NOT NULL, note TEXT, at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broker_tasks (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, client_id TEXT NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL, due TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_tenant ON broker_tasks(workspace_id, done, due);
            ''')

    # helpers -----------------------------------------------------------------
    def _client(self, db: sqlite3.Connection, wid: str, cid: str) -> sqlite3.Row:
        row = db.execute('SELECT c.id, c.alias, c.renewal_date, p.stage, p.lender, p.balance, '
                         'p.rate_pct, p.rate_type FROM broker_clients c LEFT JOIN broker_profiles p '
                         'ON p.client_id = c.id WHERE c.workspace_id=? AND c.id=?', (wid, cid)).fetchone()
        if row is None:
            raise AccessDenied('Client not found in this workspace')
        return row

    @staticmethod
    def _dec(value: str | None) -> D | None:
        return None if value in (None, '') else D(value)

    def _facts(self, row: sqlite3.Row) -> ClientFacts:
        renewal = date.fromisoformat(row['renewal_date']) if row['renewal_date'] else None
        return ClientFacts(renewal, Stage(row['stage'] or Stage.NEW.value), self._dec(row['balance']),
                           self._dec(row['rate_pct']), self._market(row['lender'], self._today()))

    # profiles ----------------------------------------------------------------
    def update_profile(self, wid: str, token: str, cid: str, *, lender: str | None = None,
                       balance: D | None = None, rate_pct: D | None = None,
                       rate_type: str | None = None) -> dict:
        self.ws._assert_access(wid, token)
        if balance is not None and not D(0) < balance <= D('50000000'):
            raise ValueError('balance must be positive and below $50M')
        if rate_pct is not None and not D(0) <= rate_pct <= D(30):
            raise ValueError('rate must be 0 to 30 percent')
        if rate_type not in (None, 'fixed', 'variable'):
            raise ValueError('rate_type must be fixed or variable')
        with _LOCK, self.ws._db() as db:
            row = self._client(db, wid, cid)
            db.execute('INSERT INTO broker_profiles VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET '
                       'lender=COALESCE(excluded.lender, lender), balance=COALESCE(excluded.balance, balance), '
                       'rate_pct=COALESCE(excluded.rate_pct, rate_pct), '
                       'rate_type=COALESCE(excluded.rate_type, rate_type), updated=excluded.updated',
                       (cid, wid, row['stage'] or Stage.NEW.value, lender and lender.lower(),
                        None if balance is None else str(balance), None if rate_pct is None else str(rate_pct),
                        rate_type, now()))
            self.ws._audit(db, wid, cid, 'profile_updated',
                           {'fields': [k for k, v in (('lender', lender), ('balance', balance),
                                                      ('rate_pct', rate_pct), ('rate_type', rate_type))
                                       if v is not None]})
        return self.client(wid, token, cid)

    def move(self, wid: str, token: str, cid: str, target: Stage, note: str = '') -> dict:
        self.ws._assert_access(wid, token)
        if len(note) > 500:
            raise ValueError('note is limited to 500 characters')
        with _LOCK, self.ws._db() as db:
            row = self._client(db, wid, cid)
            current = Stage(row['stage'] or Stage.NEW.value)
            check_transition(current, target)
            db.execute('INSERT INTO broker_profiles (client_id, workspace_id, stage, updated) VALUES (?,?,?,?) '
                       'ON CONFLICT(client_id) DO UPDATE SET stage=excluded.stage, updated=excluded.updated',
                       (cid, wid, target.value, now()))
            db.execute('INSERT INTO broker_stage_history VALUES (?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), wid, cid, current.value, target.value, note.strip(), now()))
            self.ws._audit(db, wid, cid, 'stage_changed', {'from': current.value, 'to': target.value})
        return self.client(wid, token, cid)

    def history(self, wid: str, token: str, cid: str) -> list[dict]:
        self.ws._assert_access(wid, token)
        with self.ws._db() as db:
            self._client(db, wid, cid)
            return [dict(r) for r in db.execute(
                'SELECT from_stage, to_stage, note, at FROM broker_stage_history '
                'WHERE workspace_id=? AND client_id=? ORDER BY at, rowid', (wid, cid))]

    # tasks -------------------------------------------------------------------
    def add_task(self, wid: str, token: str, cid: str, kind: str, title: str, due: date) -> dict:
        self.ws._assert_access(wid, token)
        if kind not in CONTACT_TASK_KINDS | {'document', 'review'}:
            raise ValueError('kind must be call, email, meeting, document or review')
        if not title.strip() or len(title) > 200:
            raise ValueError('title is required, max 200 characters')
        if kind in CONTACT_TASK_KINDS and not self.ws.has_consent(wid, token, cid, 'contact_homeowner'):
            raise AccessDenied('Contact tasks need recorded contact_homeowner consent')
        task = {'id': str(uuid.uuid4()), 'client_id': cid, 'kind': kind, 'title': title.strip(),
                'due': due.isoformat(), 'done': False}
        with _LOCK, self.ws._db() as db:
            self._client(db, wid, cid)
            db.execute('INSERT INTO broker_tasks VALUES (?,?,?,?,?,?,0,?)',
                       (task['id'], wid, cid, kind, task['title'], task['due'], now()))
            self.ws._audit(db, wid, cid, 'task_added', {'kind': kind, 'due': task['due']})
        return task

    def complete_task(self, wid: str, token: str, task_id: str) -> None:
        self.ws._assert_access(wid, token)
        with _LOCK, self.ws._db() as db:
            cur = db.execute('UPDATE broker_tasks SET done=1 WHERE workspace_id=? AND id=? AND done=0',
                             (wid, task_id))
            if cur.rowcount != 1:
                raise AccessDenied('Open task not found in this workspace')

    # reads -------------------------------------------------------------------
    def client(self, wid: str, token: str, cid: str) -> dict:
        self.ws._assert_access(wid, token)
        with self.ws._db() as db:
            row = self._client(db, wid, cid)
        return self._view(row)

    def _view(self, row: sqlite3.Row) -> dict:
        facts = self._facts(row)
        p = priority(facts, self._today())
        return {'id': row['id'], 'alias': row['alias'], 'renewal_date': row['renewal_date'],
                'stage': facts.stage.value, 'lender': row['lender'],
                'balance': row['balance'], 'rate_pct': row['rate_pct'], 'rate_type': row['rate_type'],
                'market_rate_pct': None if facts.market_rate_pct is None else str(facts.market_rate_pct),
                'window': window(facts.renewal_date, self._today()).value,
                'priority': p.score, 'priority_reasons': list(p.reasons)}

    def summary(self, wid: str, token: str, top: int = 10) -> dict:
        self.ws._assert_access(wid, token)
        if not 1 <= top <= 100:
            raise ValueError('top must be 1 to 100')
        today = self._today()
        with self.ws._db() as db:
            rows = db.execute('SELECT c.id, c.alias, c.renewal_date, p.stage, p.lender, p.balance, '
                              'p.rate_pct, p.rate_type FROM broker_clients c LEFT JOIN broker_profiles p '
                              'ON p.client_id = c.id WHERE c.workspace_id=?', (wid,)).fetchall()
            tasks = db.execute('SELECT t.id, t.client_id, c.alias, t.kind, t.title, t.due FROM broker_tasks t '
                               'JOIN broker_clients c ON c.id = t.client_id '
                               'WHERE t.workspace_id=? AND t.done=0 ORDER BY t.due', (wid,)).fetchall()
        views = [self._view(r) for r in rows]
        open_views = [v for v in views if Stage(v['stage']) not in CLOSED]
        maturing_90 = sum((D(v['balance']) for v in open_views if v['balance'] and
                           v['window'] in (Window.OVERDUE.value, Window.UNDER_30.value, Window.D30_90.value)),
                          D(0))
        closed = [v for v in views if Stage(v['stage']) in CLOSED]
        won = [v for v in closed if v['stage'] in (Stage.RENEWED.value, Stage.SWITCHED.value)]
        return {
            'as_of': today.isoformat(),
            'clients': len(views),
            'by_stage': dict(Counter(v['stage'] for v in views)),
            'by_window': dict(Counter(v['window'] for v in open_views)),
            'balance_maturing_90_days': str(maturing_90),
            'retention_rate': None if not closed else round(len(won) / len(closed), 3),
            'top_priorities': sorted(open_views, key=lambda v: (-v['priority'], v['renewal_date'] or '9999'))[:top],
            'overdue_tasks': [dict(t) for t in tasks if t['due'] < today.isoformat()],
            'upcoming_tasks': [dict(t) for t in tasks if t['due'] >= today.isoformat()][:20],
        }
