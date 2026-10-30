from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from renewal.broker.dashboard import BrokerDashboard
from renewal.broker.pipeline import InvalidTransition, Stage
from renewal.broker.workspace import AccessDenied, BrokerWorkspace

TODAY = date(2026, 10, 12)


@pytest.fixture
def env(tmp_path):
    ws = BrokerWorkspace(tmp_path / 'b.sqlite3')
    dash = BrokerDashboard(ws, market_rate=lambda lender, day: D('4.49'), today=lambda: TODAY)
    a = ws.create_workspace('Broker A')
    b = ws.create_workspace('Broker B')
    return ws, dash, a, b


def add(ws, w, alias, renewal):
    return ws.add_client(w['workspace_id'], w['access_token'], alias, renewal)['id']


def test_profile_stage_and_history(env):
    ws, dash, a, _ = env
    wid, tok = a['workspace_id'], a['access_token']
    cid = add(ws, a, 'Client 1', '2026-11-01')
    view = dash.update_profile(wid, tok, cid, lender='RBC', balance=D('500000'), rate_pct=D('5.49'),
                               rate_type='fixed')
    assert view['stage'] == 'new' and view['lender'] == 'rbc' and view['priority'] == 80
    dash.update_profile(wid, tok, cid, rate_pct=D('5.29'))
    assert dash.client(wid, tok, cid)['balance'] == '500000'     # untouched fields kept
    dash.move(wid, tok, cid, Stage.ANALYSIS_READY, 'statement received')
    dash.move(wid, tok, cid, Stage.NEGOTIATING)
    with pytest.raises(InvalidTransition):
        dash.move(wid, tok, cid, Stage.NEW)
    hist = dash.history(wid, tok, cid)
    assert [(h['from_stage'], h['to_stage']) for h in hist] == [('new', 'analysis_ready'),
                                                               ('analysis_ready', 'negotiating')]
    actions = [e['action'] for e in ws.audit(wid, tok)]
    assert actions.count('stage_changed') == 2 and 'profile_updated' in actions


def test_validation(env):
    ws, dash, a, _ = env
    cid = add(ws, a, 'C', None)
    for kw in ({'balance': D('0')}, {'rate_pct': D('31')}, {'rate_type': 'arm'}):
        with pytest.raises(ValueError):
            dash.update_profile(a['workspace_id'], a['access_token'], cid, **kw)


def test_tenant_isolation(env):
    ws, dash, a, b = env
    cid = add(ws, a, 'Private', '2027-01-01')
    with pytest.raises(AccessDenied):
        dash.client(b['workspace_id'], b['access_token'], cid)
    with pytest.raises(AccessDenied):
        dash.client(a['workspace_id'], b['access_token'], cid)
    with pytest.raises(AccessDenied):
        dash.move(b['workspace_id'], b['access_token'], cid, Stage.ANALYSIS_READY)
    assert dash.summary(b['workspace_id'], b['access_token'])['clients'] == 0


def test_contact_tasks_need_consent(env):
    ws, dash, a, _ = env
    wid, tok = a['workspace_id'], a['access_token']
    cid = add(ws, a, 'C', '2026-12-01')
    with pytest.raises(AccessDenied, match='consent'):
        dash.add_task(wid, tok, cid, 'call', 'Discuss offer', date(2026, 10, 20))
    doc = dash.add_task(wid, tok, cid, 'document', 'Request statement', date(2026, 10, 1))
    ws.record_consent(wid, tok, cid, 'contact_homeowner', 'granted', 'Signed form 2026-10-10')
    call = dash.add_task(wid, tok, cid, 'call', 'Discuss offer', date(2026, 10, 20))
    with pytest.raises(ValueError):
        dash.add_task(wid, tok, cid, 'fax', 'x', TODAY)
    s = dash.summary(wid, tok)
    assert [t['id'] for t in s['overdue_tasks']] == [doc['id']]
    assert [t['id'] for t in s['upcoming_tasks']] == [call['id']]
    dash.complete_task(wid, tok, doc['id'])
    with pytest.raises(AccessDenied):
        dash.complete_task(wid, tok, doc['id'])
    assert dash.summary(wid, tok)['overdue_tasks'] == []


def test_summary(env):
    ws, dash, a, _ = env
    wid, tok = a['workspace_id'], a['access_token']
    soon = add(ws, a, 'Soon', '2026-11-01')
    later = add(ws, a, 'Later', '2027-08-01')
    done = add(ws, a, 'Done', '2026-10-30')
    lost = add(ws, a, 'Lost', '2026-10-30')
    dash.update_profile(wid, tok, soon, balance=D('400000'), rate_pct=D('5.99'))
    dash.update_profile(wid, tok, later, balance=D('250000'), rate_pct=D('4.00'))
    dash.update_profile(wid, tok, done, balance=D('100000'), rate_pct=D('5.00'))
    for stage in (Stage.ANALYSIS_READY, Stage.SWITCHED):
        dash.move(wid, tok, done, stage)
    dash.move(wid, tok, lost, Stage.CLOSED_LOST)
    s = dash.summary(wid, tok, top=5)
    assert s['clients'] == 4
    assert s['by_stage'] == {'new': 2, 'switched': 1, 'closed_lost': 1}
    assert s['by_window'] == {'under_30_days': 1, 'over_180_days': 1}
    assert s['balance_maturing_90_days'] == '400000'
    assert s['retention_rate'] == 0.5
    assert [c['alias'] for c in s['top_priorities']] == ['Soon', 'Later']
    with pytest.raises(ValueError):
        dash.summary(wid, tok, top=0)


def test_dashboard_api(monkeypatch):
    from renewal import main
    monkeypatch.setenv('RR_ENABLE_DEMO_WORKSPACES', '1')
    monkeypatch.setattr(main.broker_dashboard, '_today', lambda: TODAY)   # recorded rates cover this day
    with TestClient(main.app) as c:
        w = c.post('/api/v4/broker/workspaces', json={'name': 'API broker'}).json()
        h = {'X-Broker-Token': w['access_token']}
        base = f"/api/v5/broker/workspaces/{w['workspace_id']}"
        cid = c.post(f"/api/v4/broker/workspaces/{w['workspace_id']}/clients", headers=h,
                     json={'alias': 'API client', 'renewal_date': '2026-12-01'}).json()['id']
        r = c.patch(f'{base}/clients/{cid}/profile', headers=h,
                    json={'lender': 'td', 'balance': '350000', 'rate_pct': '5.89'})
        assert r.status_code == 200 and r.json()['market_rate_pct'] is not None
        assert c.post(f'{base}/clients/{cid}/stage', headers=h, json={'stage': 'renewed'}).status_code == 422
        assert c.post(f'{base}/clients/{cid}/stage', headers=h, json={'stage': 'analysis_ready'}).status_code == 200
        assert c.post(f'{base}/clients/{cid}/tasks', headers=h,
                      json={'kind': 'call', 'title': 'x', 'due': '2026-10-20'}).status_code == 403
        t = c.post(f'{base}/clients/{cid}/tasks', headers=h, json={'kind': 'review', 'title': 'Check offer',
                                                                  'due': '2026-10-20'})
        assert t.status_code == 201
        assert c.post(f"{base}/tasks/{t.json()['id']}/done", headers=h).status_code == 204
        detail = c.get(f'{base}/clients/{cid}', headers=h).json()
        assert detail['stage'] == 'analysis_ready' and len(detail['history']) == 1
        dash = c.get(f'{base}/dashboard', headers=h).json()
        assert dash['clients'] == 1
        assert c.get(f'{base}/dashboard', headers={'X-Broker-Token': 'wrong'}).status_code == 404
        assert c.get(f'{base}/clients/nope', headers=h).status_code == 404
