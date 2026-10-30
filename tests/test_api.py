import io,os,tempfile
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/rr_pytest_cases.db')
from fastapi.testclient import TestClient
from renewal.main import app
from renewal.domain.schemas import Mortgage,Offer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_health_and_demo():
    with TestClient(app) as c:
        assert c.get('/api/health').json()['status']=='ok'
        demo=c.get('/api/demo').json()
        assert demo['mortgage']['balance']==480000
        assert len(demo['offers'])==2
        assert c.get('/').status_code==200
        assert 'Renewal Radar' in c.get('/').text


def test_analyze_and_report_pdf():
    with TestClient(app) as c:
        data=c.get('/api/demo').json()
        body={'mortgage':data['mortgage'],'offers':data['offers'],'horizon_months':36}
        r=c.post('/api/analyze',json=body)
        assert r.status_code==200,r.text
        assert r.json()['scenarios'][0]['loan']['regular_payment']==3378.66
        assert len(r.json()['stress']['paths'])==5
        assert r.json()['switch']['status']=='potentially-exempt'
        r=c.post('/api/report/pdf',json=body)
        assert r.status_code==200
        assert r.content.startswith(b'%PDF-')
        assert len(r.content)>5000


def test_pdf_upload_and_rejections():
    with TestClient(app) as c:
        pdf=(ROOT/'fixtures'/'fictional-renewal-letter.pdf').read_bytes()
        r=c.post('/api/documents/extract',files={'file':('letter.pdf',pdf,'application/pdf')})
        assert r.status_code==200
        assert r.json()['fields']['balance']['value']==480000
        assert c.post('/api/documents/extract',files={'file':('wrong.pdf',b'not pdf','application/pdf')}).status_code==422
        assert c.post('/api/documents/extract',files={'file':('huge.pdf',b'%PDF-'+b'A'*(9*1024*1024),'application/pdf')}).status_code==413
        assert c.get('/api/demo/sample.pdf').content.startswith(b'%PDF-')


def test_penalty_and_negotiate_and_ics():
    with TestClient(app) as c:
        assert c.post('/api/penalty',json={'balance':200000,'current_rate':6,'rate_type':'fixed',
           'remaining_term_months':36,'comparison_rate':4,'contract_method':'simple'}).json()['estimated_penalty']==12000
        req={'mortgage':Mortgage().model_dump(),'competing_rate':4.49,'competing_lender':'another lender'}
        x=c.post('/api/negotiation',json=req)
        assert x.status_code==200
        assert '5.49%' in x.json()['email']
        x=c.get('/api/calendar/2027-03-01.ics')
        assert x.status_code==200
        assert b'BEGIN:VCALENDAR' in x.content


def test_case_auth_and_expiring_links():
    with TestClient(app) as c:
        d=c.get('/api/demo').json()
        case=c.post('/api/cases',json={'title':'Test','mortgage':d['mortgage'],'offers':d['offers']}).json()
        id,token=case['id'],case['access_token']
        assert c.get('/api/cases/'+id).status_code==404
        assert c.get('/api/cases/'+id,headers={'X-Case-Token':'bad'}).status_code==404
        assert c.get('/api/cases/'+id,headers={'X-Case-Token':token}).status_code==200
        share=c.post('/api/cases/'+id+'/share',json={'expires_hours':1},headers={'X-Case-Token':token}).json()
        assert share['url_path'].startswith('/shared/')
        assert c.get('/api/shares/'+share['token']).status_code==200
        assert c.get('/shared/'+share['token']).status_code==200
        assert c.delete('/api/cases/'+id+'/shares/'+share['token'],headers={'X-Case-Token':token}).json()['revoked']
        assert c.get('/api/shares/'+share['token']).status_code==404


def test_invalid_mortgage_inputs_rejected():
    with TestClient(app) as c:
        m=Mortgage().model_dump();m['amortization_months']=0
        assert c.post('/api/analyze',json={'mortgage':m,'offers':[]}).status_code==422


def test_agent_fallback_and_tool_manifest():
    with TestClient(app) as c:
        d=c.get('/api/demo').json()
        res=c.post('/api/agent/insight',json={'mortgage':d['mortgage'],'offers':d['offers']})
        assert res.status_code==200
        assert res.json()['text']
        tools=c.get('/api/agent/tools').json()['tools']
        assert any(t['name']=='extract_pdf_fields' for t in tools)

def test_full_agent_tool_orchestration(monkeypatch):
    async def offline_boc():
        return {'data_status':'unavailable','source_url':'https://www.bankofcanada.ca/valet/docs/',
                'checked_at':'2026-10-11T12:00:00+00:00'}
    import renewal.main as main
    monkeypatch.setattr(main,'fetch_boc',offline_boc)
    with TestClient(app) as c:
        demo=c.get('/api/demo').json()
        result=c.post('/api/agent/run',json={'mortgage':demo['mortgage'],'offers':demo['offers']})
        assert result.status_code==200,result.text
        data=result.json()
        assert len(data['steps'])==8
        assert data['steps'][2]['tool']=='classify_switch'
        assert data['summary']['text']
        assert data['comparison']['scenarios'][1]['assumption_type']=='hypothetical'
