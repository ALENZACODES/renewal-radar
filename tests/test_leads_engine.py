import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from renewal.leads.consent import CONSENT_TEXTS, CURRENT_VERSION, validate_consent
from renewal.leads.engine import LeadEngine, LeadInput
from renewal.leads.identity import Vault
from renewal.leads.webhooks import Outbox

NOW = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Rx:
    def __init__(self):
        self.seen = []

    def post(self, url, body, headers):
        self.seen.append(body)
        return 200


def consent(methods=('email',)):
    return validate_consent(version=CURRENT_VERSION, text_digest=CONSENT_TEXTS[CURRENT_VERSION].digest,
                            agreed=True, agreed_at=NOW - timedelta(minutes=1), contact_methods=list(methods),
                            brokerage='Maple Mortgage Group', now=NOW)


def lead(**kw):
    base = dict(workspace_id='w1', name='Jane Doe', email='jane.doe@example.ca', phone=None, province='ON',
                consent=consent(), renewal_date=date(2026, 12, 1), balance=D('480000'),
                current_rate=D('5.49'), market_rate=D('4.49'), has_statement=True)
    base.update(kw)
    return LeadInput(**base)


@pytest.fixture
def env(tmp_path):
    clock, rx = Clock(), Rx()
    outbox = Outbox(lambda url: b'hook', rx, lambda: clock.now.timestamp())
    eng = LeadEngine(tmp_path / 'leads.sqlite3', Vault(Vault.new_key()), b's' * 32, outbox,
                     lambda wid: 'https://crm.example/hook' if wid == 'w1' else None, clock)
    return eng, clock, outbox, rx, tmp_path / 'leads.sqlite3'


def test_submit_scores_encrypts_and_masks(env):
    eng, _, outbox, rx, path = env
    r = eng.submit(lead())
    assert r['duplicate'] is False and r['band'] == 'hot' and r['withdraw_token']
    raw = sqlite3.connect(path).execute('SELECT contact_sealed, balance_band FROM leads').fetchone()
    assert 'jane' not in raw[0].lower() and raw[1] == '250k_500k'
    listed = eng.for_broker('w1')[0]
    assert listed['contact'] == {'name': 'Jane', 'email': 'j•••••••@example.ca', 'phone': None}
    assert eng.for_broker('w1', reveal=True)[0]['contact']['email'] == 'jane.doe@example.ca'
    assert eng.for_broker('w2') == []
    outbox.run_due()
    assert b'"type":"lead.created"' in rx.seen[0] and b'jane' not in rx.seen[0].lower()


def test_duplicates_fold_within_window(env):
    eng, clock, outbox, _, _ = env
    first = eng.submit(lead())
    again = eng.submit(lead(email='Jane.Doe@Example.ca', phone='416-555-0199',
                            consent=consent(('email', 'phone'))))
    assert again == {'id': first['id'], 'duplicate': True}
    assert eng.for_broker('w1')[0]['submissions'] == 2
    other_broker = eng.submit(lead(workspace_id='w2'))
    assert other_broker['duplicate'] is False
    clock.now += timedelta(days=91)
    later = eng.submit(lead())
    assert later['duplicate'] is False and later['id'] != first['id']
    assert len(outbox.items) == 2           # only w1 has a webhook


def test_contact_method_must_match_details(env):
    eng = env[0]
    with pytest.raises(ValueError, match='phone contact'):
        eng.submit(lead(consent=consent(('email', 'phone'))))
    with pytest.raises(ValueError, match='province'):
        eng.submit(lead(province='XX'))
    with pytest.raises(ValueError):
        eng.submit(lead(name=' '))


def test_withdraw_erases_contact_and_allows_fresh_submit(env):
    eng, _, outbox, _, path = env
    r = eng.submit(lead())
    with pytest.raises(PermissionError):
        eng.withdraw(r['id'], 'wrong-token')
    eng.withdraw(r['id'], r['withdraw_token'])
    row = sqlite3.connect(path).execute('SELECT status, contact_sealed FROM leads').fetchone()
    assert row == ('withdrawn', None)
    assert 'contact' not in eng.for_broker('w1')[0]
    with pytest.raises(PermissionError):
        eng.withdraw(r['id'], r['withdraw_token'])
    assert any(k.startswith('lead.withdrawn') for k in outbox.items)
    assert eng.submit(lead())['duplicate'] is False


def test_reveal_scoped_to_brokerage(env):
    eng = env[0]
    r = eng.submit(lead())
    assert eng.reveal('w1', r['id'])['email'] == 'jane.doe@example.ca'
    with pytest.raises(PermissionError):
        eng.reveal('w2', r['id'])


def test_broker_status_updates(env):
    eng = env[0]
    r = eng.submit(lead())
    eng.set_status('w1', r['id'], 'contacted')
    assert eng.for_broker('w1', status='contacted')[0]['id'] == r['id']
    with pytest.raises(PermissionError):
        eng.set_status('w2', r['id'], 'qualified')
    with pytest.raises(ValueError):
        eng.set_status('w1', r['id'], 'sold')


def test_engine_requires_strong_secret(tmp_path):
    with pytest.raises(ValueError):
        LeadEngine(tmp_path / 'x.db', Vault(Vault.new_key()), b'short')


def test_leads_api(monkeypatch, tmp_path):
    from renewal import main
    monkeypatch.setenv('RR_ENABLE_DEMO_WORKSPACES', '1')
    monkeypatch.setenv('RR_LEAD_KEY', Vault.new_key().decode())
    monkeypatch.setenv('RR_LEAD_DEDUPE_SECRET', 'd' * 32)
    monkeypatch.setattr(main, '_lead_engine', None)
    monkeypatch.setattr(main, 'LEADS_DB', tmp_path / 'api-leads.sqlite3')
    with TestClient(main.app) as c:
        text = c.get('/api/v5/leads/consent-text').json()
        assert text['version'] == CURRENT_VERSION
        w = c.post('/api/v4/broker/workspaces', json={'name': 'Lead broker'}).json()
        body = {'workspace_id': w['workspace_id'], 'name': 'Sam Lee', 'email': 'sam@example.ca',
                'province': 'AB', 'renewal_date': '2026-12-15', 'balance': '350000', 'current_rate': '5.6',
                'consent': {'version': text['version'], 'text_digest': text['digest'], 'agreed': True,
                            'agreed_at': datetime.now(timezone.utc).isoformat(),
                            'contact_methods': ['email'], 'brokerage': 'Lead broker'}}
        r = c.post('/api/v5/leads', json=body)
        assert r.status_code == 201, r.text
        created = r.json()
        bad = c.post('/api/v5/leads', json={**body, 'consent': {**body['consent'], 'agreed': False}})
        assert bad.status_code == 422
        missing = c.post('/api/v5/leads', json={**body, 'workspace_id': 'nope'})
        assert missing.status_code == 404
        h = {'X-Broker-Token': w['access_token']}
        listed = c.get(f"/api/v5/broker/workspaces/{w['workspace_id']}/leads", headers=h).json()['leads']
        assert listed[0]['contact']['email'].startswith('s•')
        assert c.get(f"/api/v5/broker/workspaces/{w['workspace_id']}/leads",
                     headers={'X-Broker-Token': 'bad'}).status_code == 404
        rev = c.post(f"/api/v5/broker/workspaces/{w['workspace_id']}/leads/{created['id']}/reveal", headers=h)
        assert rev.json()['contact']['email'] == 'sam@example.ca'
        audit = c.get(f"/api/v4/broker/workspaces/{w['workspace_id']}/audit", headers=h).json()['events']
        assert any(e['action'] == 'lead_contact_revealed' for e in audit)
        assert c.request('DELETE', f"/api/v5/leads/{created['id']}",
                         json={'withdraw_token': created['withdraw_token']}).status_code == 204
