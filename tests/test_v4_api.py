"""HTTP contract checks for provenance and workspace boundaries."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from fastapi.testclient import TestClient
from renewal.main import app

client=TestClient(app)

def test_rate_ingestion_disabled_without_secret(monkeypatch):
    monkeypatch.delenv('RR_RATE_INGEST_KEY',raising=False)
    response=client.post('/api/v4/rates/observations',json={})
    assert response.status_code==422  # schema rejects missing attributes first
    payload={'lender':'Example','product':'Fixed','rate_type':'fixed','term_months':60,
             'annual_rate':'5.25','rate_kind':'posted',
             'effective_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
             'captured_at':datetime.now(timezone.utc).isoformat(),
             'source_url':'https://example.com/rate','source_sha256':sha256(b'page').hexdigest(),
             'evidence':'Posted five-year fixed 5.25%'}
    assert client.post('/api/v4/rates/observations',json=payload).status_code==403
    monkeypatch.setenv('RR_RATE_INGEST_KEY','very-long-development-ingest-key-2026')
    response=client.post('/api/v4/rates/observations',json=payload,
             headers={'X-Rate-Ingest-Key':'very-long-development-ingest-key-2026'})
    assert response.status_code==201,response.text
    assert response.json()['lender']=='Example'
    rates=client.get('/api/v4/rates/history',params={'lender':'Example'})
    assert rates.status_code==200
    assert rates.json()['observations']


def test_broker_demo_creation_requires_flag(monkeypatch):
    monkeypatch.delenv('RR_ENABLE_DEMO_WORKSPACES',raising=False)
    assert client.post('/api/v4/broker/workspaces',json={'name':'Demo'}).status_code==403


def test_broker_http_scope_and_revoke(monkeypatch):
    monkeypatch.setenv('RR_ENABLE_DEMO_WORKSPACES','1')
    a=client.post('/api/v4/broker/workspaces',json={'name':'Team A'})
    b=client.post('/api/v4/broker/workspaces',json={'name':'Team B'})
    assert a.status_code==201 and b.status_code==201
    wa,wb=a.json(),b.json()
    path=f"/api/v4/broker/workspaces/{wa['workspace_id']}"
    headers={'X-Broker-Token':wa['access_token']}
    assert client.get(path+'/clients',headers={'X-Broker-Token':wb['access_token']}).status_code==404
    new=client.post(path+'/clients',headers=headers,json={'alias':'Test Homeowner'})
    assert new.status_code==201,new.text
    cid=new.json()['id']
    consents=path+f'/clients/{cid}/consents'
    consent=client.post(consents,headers=headers,json={
        'scope':'bank_data_read','status':'granted','evidence':'Homeowner consented in a test flow'})
    assert consent.status_code==201,consent.text
    assert client.get(consents+'/bank_data_read',headers=headers).json()['granted']
    revoked=client.post(consents,headers=headers,json={
        'scope':'bank_data_read','status':'revoked','evidence':'Homeowner withdrew consent'})
    assert revoked.status_code==201
    assert not client.get(consents+'/bank_data_read',headers=headers).json()['granted']
    assert len(client.get(path+'/audit',headers=headers).json()['events'])>=3
