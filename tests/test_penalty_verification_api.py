import hashlib
from fastapi.testclient import TestClient
from renewal.main import app

HASH=hashlib.sha256(b'fictional').hexdigest()


def fixture_case():
    return {'case_id':'SYN_001','source_kind':'synthetic','evidence_sha256':HASH,
        'evidence_description':'Fictional test fixture', 'payout_date':'2026-05-05',
        'lender_payout':'16000.00','inputs':{
            'balance':'400000','annual_rate':'5','remaining_months':24,
            'lender':'td','comparison_posted_rate':'4','documented_discount':'1'}}


def test_verify_endpoint_with_synthetic_reference():
    with TestClient(app) as client:
        response=client.post('/api/penalty/v7/verify',json={'cases':[fixture_case()]})
    assert response.status_code==200
    data=response.json()
    assert data['count']==1
    assert data['results'][0]['status']=='match'
    assert not data['accuracy_claim_supported']


def test_verify_endpoint_rejects_invalid_payload():
    with TestClient(app) as client:
        response=client.post('/api/penalty/v7/verify',json={'cases':'bad'})
    assert response.status_code==422


def test_verify_endpoint_rejects_unexpected_mortgage_fields():
    bad=fixture_case()
    bad['inputs']['untrusted_extra']='x'
    with TestClient(app) as client:
        response=client.post('/api/penalty/v7/verify',json={'cases':[bad]})
    assert response.status_code==422
