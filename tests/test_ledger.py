import csv,io
from fastapi.testclient import TestClient
from renewal.main import app
from renewal.domain.schemas import AnalyzeRequest,Mortgage,Offer
from renewal.services.ledger import ledger_csv,annual_summary


def demo():
    return AnalyzeRequest(mortgage=Mortgage(),offers=[Offer(name='Alternative',rate=4.49)],horizon_months=36)


def test_csv_matches_calculation_and_bom():
    result=ledger_csv(demo())
    assert result.startswith(b'\xef\xbb\xbf')
    records=list(csv.DictReader(io.StringIO(result.decode('utf-8-sig'))))
    assert len(records)==72
    assert records[0]['offer']=='Your renewal offer'
    assert float(records[0]['balance'])<480000
    assert float(records[-1]['balance'])<float(records[35]['balance'])


def test_annual_totals_consistent():
    result=annual_summary(demo())
    assert len(result['scenarios'])==2
    for scenario in result['scenarios']:
        assert len(scenario['years'])==3
        assert all(row['payments']==12 for row in scenario['years'])
        assert abs(sum(row['paid'] for row in scenario['years'])-scenario['total_paid'])<0.5
        assert abs(sum(row['interest'] for row in scenario['years'])-scenario['total_interest'])<0.5


def test_short_term_flag_and_formula_injection():
    request=AnalyzeRequest(mortgage=Mortgage(),offers=[Offer(name='=HYPERLINK(\"x\")',rate=4,term_months=12)],horizon_months=36)
    assert "'=HYPERLINK" in ledger_csv(request).decode('utf-8-sig')
    assert annual_summary(request)['scenarios'][1]['shorter_term_than_requested']


def test_endpoints():
    with TestClient(app) as client:
        data=demo().model_dump()
        csv_response=client.post('/api/ledger.csv',json=data)
        assert csv_response.status_code==200
        assert 'attachment' in csv_response.headers['content-disposition']
        assert len(csv_response.content)>3000
        result=client.post('/api/ledger/annual',json=data)
        assert result.status_code==200
        assert len(result.json()['scenarios'])==2
        assert client.post('/api/ledger.csv',json={}).status_code==422
