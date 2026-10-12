from fastapi.testclient import TestClient
from renewal.main import app

def test_lender_profile_api():
    with TestClient(app) as client:
        r=client.get('/api/penalty/v3/lenders')
        assert r.status_code==200
        assert any(p['code']=='scotia' for p in r.json()['lenders'])

def test_penalty_api_decimal_strings():
    with TestClient(app) as client:
        r=client.post('/api/penalty/v3/estimate',json={
          'balance':'400000','annual_rate':'5','remaining_months':24,
          'lender':'td','documented_discount':'1','comparison_posted_rate':'4'})
        assert r.status_code==200, r.text
        assert r.json()['total_estimate']=='16000.00'

def test_penalty_api_rejects_extra_fields():
    with TestClient(app) as client:
        r=client.post('/api/penalty/v3/estimate',json={
          'balance':'400000','annual_rate':'5','remaining_months':24,'hacker':'value'})
        assert r.status_code==422
