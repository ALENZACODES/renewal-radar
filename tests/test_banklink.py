import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from renewal.banklink.adapters import (FlinksAdapter, PlaidAdapter, ProductionNotConfigured,
                                       SandboxTransport, adapter_for)
from renewal.banklink.models import CredentialRefused, Provider, Scope, reject_credentials
from renewal.banklink.service import BankLinkService, ConsentError, to_renewal_inputs

F = Path(__file__).resolve().parents[1] / 'backend' / 'renewal' / 'banklink' / 'sandbox'
NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def sandbox(name):
    return SandboxTransport(json.loads((F / f'{name}_sandbox.json').read_text()))


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def service(clock=None):
    plaid, flinks = sandbox('plaid'), sandbox('flinks')
    svc = BankLinkService({Provider.PLAID: PlaidAdapter(plaid), Provider.FLINKS: FlinksAdapter(flinks)},
                          clock=clock or Clock())
    return svc, plaid, flinks


def linked(svc, provider=Provider.PLAID):
    consent = svc.grant('case-1', provider, {Scope.MORTGAGE_READ}, 'renewal_analysis')
    svc.start(consent.id)
    return consent, svc.complete(consent.id, 'public-sandbox-token')


def test_plaid_mapping():
    snaps = PlaidAdapter(sandbox('plaid')).mortgages('access-sandbox-9c1e', date(2026, 10, 12))
    assert len(snaps) == 1
    s = snaps[0]
    assert s.balance == D('412345.67') and s.rate_pct == D('5.29') and s.rate_type == 'fixed'
    assert s.maturity_date == date(2027, 3, 1) and s.payment == D('2868.60')
    assert s.lender_name == 'Tartan Bank of Canada' and s.missing == ()


def test_flinks_mapping_keeps_only_mortgage_and_reports_gaps():
    snaps = FlinksAdapter(sandbox('flinks')).mortgages('req-sandbox-77', date(2026, 10, 12))
    assert len(snaps) == 1
    assert snaps[0].balance == D('398765.43')
    assert set(snaps[0].missing) == {'rate_pct', 'maturity_date', 'payment'}


def test_production_transport_refused():
    class Live:
        sandbox = False

        def call(self, op, body):
            raise AssertionError('must not be called')
    with pytest.raises(ProductionNotConfigured):
        PlaidAdapter(Live())
    with pytest.raises(ProductionNotConfigured):
        adapter_for(Provider.FLINKS, Live())


@pytest.mark.parametrize('payload', [{'password': 'x'}, {'nested': [{'Username': 'a'}]},
                                     {'mfa-code': '123'}, {'auth': {'PIN': '1'}}])
def test_credentials_refused_anywhere(payload):
    with pytest.raises(CredentialRefused):
        reject_credentials(payload)


def test_full_flow_hashes_refs_and_audits():
    svc, plaid, _ = service()
    consent, link = linked(svc)
    snaps = svc.mortgages(link)
    assert snaps[0].account_ref != 'acc-mortgage-1' and len(snaps[0].account_ref) == 16
    svc.mortgages(link)                       # cached, no second provider call
    assert [op for op, _ in plaid.calls].count('liabilities/get') == 1
    actions = [e['action'] for e in svc.audit(consent.id)]
    assert actions == ['consent_granted', 'link_started', 'link_completed', 'mortgages_fetched']
    assert 'access-sandbox' not in json.dumps(svc.audit(consent.id))


def test_consent_rules():
    svc, _, _ = service()
    with pytest.raises(ConsentError):
        svc.grant('c', Provider.PLAID, {Scope.ACCOUNTS_READ}, 'renewal_analysis')
    with pytest.raises(ConsentError):
        svc.grant('c', Provider.PLAID, {Scope.MORTGAGE_READ}, 'marketing')
    with pytest.raises(ConsentError):
        svc.grant('c', Provider.PLAID, {Scope.MORTGAGE_READ}, 'renewal_analysis', days=365)
    with pytest.raises(CredentialRefused):
        svc.grant('c', Provider.PLAID, {Scope.MORTGAGE_READ}, 'renewal_analysis', payload={'password': 'p'})
    only_plaid = BankLinkService({Provider.PLAID: PlaidAdapter(sandbox('plaid'))})
    with pytest.raises(ConsentError):
        only_plaid.grant('c', Provider.FLINKS, {Scope.MORTGAGE_READ}, 'renewal_analysis')


def test_revoke_removes_provider_access_and_data():
    svc, plaid, _ = service()
    consent, link = linked(svc)
    svc.mortgages(link)
    svc.revoke(consent.id)
    assert ('item/remove', {'access_token': 'access-sandbox-9c1e'}) in plaid.calls
    with pytest.raises(ConsentError):
        svc.mortgages(link)
    with pytest.raises(ConsentError):
        svc.start(consent.id)
    with pytest.raises(ConsentError):
        svc.revoke('nope')


def test_expiry_and_purge():
    clock = Clock()
    svc, plaid, _ = service(clock)
    consent = svc.grant('c', Provider.PLAID, {Scope.MORTGAGE_READ}, 'penalty_estimate', days=1)
    link = svc.complete(consent.id, 'tok')
    svc.mortgages(link)
    clock.now += timedelta(days=2)
    with pytest.raises(ConsentError):
        svc.mortgages(link)
    assert svc.purge_expired() == 1
    assert ('item/remove', {'access_token': 'access-sandbox-9c1e'}) in plaid.calls


def test_retention_purges_snapshots_but_keeps_link():
    clock = Clock()
    svc, plaid, _ = service(clock)
    consent = svc.grant('c', Provider.PLAID, {Scope.MORTGAGE_READ}, 'renewal_analysis', days=90)
    link = svc.complete(consent.id, 'tok')
    svc.mortgages(link)
    clock.now += timedelta(days=31)
    assert svc.purge_expired() == 1
    svc.mortgages(link)
    assert [op for op, _ in plaid.calls].count('liabilities/get') == 2


def test_flinks_session_is_hosted_widget():
    svc, _, _ = service()
    consent = svc.grant('c', Provider.FLINKS, {Scope.MORTGAGE_READ}, 'renewal_analysis')
    session = svc.start(consent.id)
    assert session.widget_url.startswith('https://') and session.sandbox


def test_to_renewal_inputs():
    svc, _, _ = service()
    _, link = linked(svc, Provider.FLINKS)
    out = to_renewal_inputs(svc.mortgages(link)[0])
    assert out['balance'] == '398765.43' and out['confirm_required']
    assert 'rate_pct' in out['ask_user_for']


def test_banklink_api(monkeypatch):
    import base64, hashlib, os
    from renewal import main
    monkeypatch.setenv('RR_ENABLE_DEMO_WORKSPACES', '1')
    with TestClient(main.app) as c:
        assert c.get('/api/v5/banklink/providers').json()['credential_collection'] is False
        monkeypatch.delenv('RR_ENABLE_BANKLINK_SANDBOX', raising=False)
        assert c.post('/api/v5/banklink/consents', json={'case_id': 'x', 'workspace_id': 'y',
                                                         'provider': 'plaid',
                                                         'purpose': 'renewal_analysis'}).status_code == 403
        monkeypatch.setenv('RR_ENABLE_BANKLINK_SANDBOX', '1')
        ws = c.post('/api/v4/broker/workspaces', json={'name': 'BL'}).json()
        d = c.get('/api/demo').json()
        case = c.post('/api/cases', json={'title': 'bl', 'workspace_id': ws['workspace_id'],
                                          'mortgage': d['mortgage'], 'offers': []},
                      headers={'X-Broker-Token': ws['access_token']}).json()
        minted = c.post(f"/api/cases/{case['id']}/tokens",
                        json={'scopes': ['banklink:connect', 'banklink:read'], 'ttl_seconds': 3600},
                        headers={'X-Broker-Token': ws['access_token']}).json()
        token = minted['token']
        consent = c.post('/api/v5/banklink/consents', json={
            'case_id': case['id'], 'workspace_id': ws['workspace_id'],
            'provider': 'plaid', 'purpose': 'renewal_analysis'},
            headers={'X-Broker-Token': ws['access_token']})
        assert consent.status_code == 201, consent.text
        cid = consent.json()['consent_id']
        verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        sess = c.post(f'/api/v5/banklink/consents/{cid}/session',
                      json={'code_challenge': challenge, 'bind_cookie': False},
                      headers={'X-Case-Token': token})
        assert sess.status_code == 200 and sess.json()['sandbox'] is True
        # legacy complete without state is gone
        assert c.post(f'/api/v5/banklink/consents/{cid}/complete',
                      json={'public_token': 't'}).status_code == 410
        bad = c.post('/api/v5/banklink/complete',
                     json={'state': sess.json()['state'], 'code_verifier': verifier,
                           'public_token': 't', 'extra': {'password': 'x'}})
        assert bad.status_code == 422
        # new session after failed complete attempt still ok — claim not done on 422 before claim?
        # Credential refuse happens inside complete after claim — recreate session
        sess = c.post(f'/api/v5/banklink/consents/{cid}/session',
                      json={'code_challenge': challenge, 'bind_cookie': False},
                      headers={'X-Case-Token': token})
        link = c.post('/api/v5/banklink/complete',
                      json={'state': sess.json()['state'], 'code_verifier': verifier,
                            'public_token': 't'}).json()['link_id']
        m = c.get(f'/api/v5/banklink/links/{link}/mortgages',
                  headers={'X-Broker-Token': ws['access_token']}).json()
        assert m['mortgages'][0]['balance'] == '412345.67'
        assert m['prefill'][0]['confirm_required'] is True
        assert c.delete(f'/api/v5/banklink/consents/{cid}',
                        headers={'X-Broker-Token': ws['access_token']}).status_code == 204
        assert c.get(f'/api/v5/banklink/links/{link}/mortgages',
                     headers={'X-Broker-Token': ws['access_token']}).status_code == 403
