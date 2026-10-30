from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
import pytest
from renewal.intelligence.rate_history import RateArchive,RateObservation,source_hash
from renewal.broker.workspace import BrokerWorkspace,AccessDenied

NOW=datetime.now(timezone.utc)
def iso(dt):return dt.isoformat()

def rate(**overrides):
    v=dict(lender='Sample Bank',product='5 Year Fixed',rate_type='fixed',
        term_months=60,annual_rate='5.25',rate_kind='posted',
        effective_at=iso(NOW-timedelta(days=1)),captured_at=iso(NOW),
        source_url='https://example.com/mortgages',
        source_sha256=sha256(b'evidence').hexdigest(),evidence='Five-year posted fixed rate 5.25%')
    v.update(overrides)
    return RateObservation(**v)

def test_rate_archive_append_and_query(tmp_path):
    db=RateArchive(tmp_path/'rates.sqlite3')
    first=db.append(rate())
    assert first['id']==db.append(rate())['id']
    assert len(db.history('SAMPLE BANK'))==1
    assert db.history('another lender')==[]
    assert len(db.history('Sample Bank',term_months=60,rate_type='fixed'))==1
    assert db.history('Sample Bank',term_months=24)==[]

def test_rate_archive_revisions(tmp_path):
    db=RateArchive(tmp_path/'rate.db')
    a=db.append(rate())
    b=db.append(rate(annual_rate='5.10',source_sha256=sha256(b'revision').hexdigest()),a['id'])
    assert a['id']!=b['id']
    assert b['superseded_id']==a['id']
    assert len(db.history('Sample Bank'))==2
    with pytest.raises(ValueError,match='nonexistent'):
        db.append(rate(annual_rate='4.50'), 'not-a-real-id')

def test_historical_discount_with_source(tmp_path):
    db=RateArchive(tmp_path/'rates.db')
    observation=db.append(rate())
    result=db.reconstruct_discount('Sample Bank',iso(NOW), '4.25', 60)
    assert result['status']=='estimated_historical_discount'
    assert result['discount_pp']=='1.00'
    assert result['source_id']==observation['id']
    assert db.reconstruct_discount('Other Bank',iso(NOW),'4.25',60)['discount_pp'] is None

def test_rate_validation_blocks_untraceable_values():
    cases=[dict(source_url='http://example.com'),dict(source_url='https://localhost/x'),
        dict(source_sha256='missing'),dict(annual_rate='NaN'),dict(annual_rate='45'),
        dict(term_months=0),dict(rate_kind='imaginary'),dict(evidence=''),
        dict(captured_at=iso(NOW+timedelta(days=2))),dict(currency='USD')]
    for case in cases:
        with pytest.raises(ValueError):rate(**case).validate()

def test_broker_tenant_isolation(tmp_path):
    db=BrokerWorkspace(tmp_path/'brokers.db')
    a=db.create_workspace('A Brokerage')
    b=db.create_workspace('B Brokerage')
    ac=db.add_client(a['workspace_id'],a['access_token'],'Client A','2027-06-01')
    bc=db.add_client(b['workspace_id'],b['access_token'],'Client B')
    assert [r['id'] for r in db.clients(a['workspace_id'],a['access_token'])]==[ac['id']]
    assert [r['id'] for r in db.clients(b['workspace_id'],b['access_token'])]==[bc['id']]
    with pytest.raises(AccessDenied):db.clients(a['workspace_id'],b['access_token'])
    with pytest.raises(AccessDenied):
        db.record_consent(a['workspace_id'],a['access_token'],bc['id'],'view_case','granted','Consent')

def test_broker_consent_is_revocable(tmp_path):
    db=BrokerWorkspace(tmp_path/'brokers.db')
    a=db.create_workspace('A')
    wid,token=a['workspace_id'],a['access_token']
    client=db.add_client(wid,token,'Homeowner')['id']
    assert not db.has_consent(wid,token,client,'view_case')
    db.record_consent(wid,token,client,'view_case','granted','Signed in application')
    assert db.has_consent(wid,token,client,'view_case')
    db.record_consent(wid,token,client,'view_case','revoked','Customer withdrew')
    assert not db.has_consent(wid,token,client,'view_case')
    assert any(e['action']=='consent_revoked' for e in db.audit(wid,token))

def test_broker_rejects_unknown_scopes_and_bad_dates(tmp_path):
    db=BrokerWorkspace(tmp_path/'brokers.db')
    a=db.create_workspace('Team')
    wid,token=a['workspace_id'],a['access_token']
    with pytest.raises(ValueError):db.add_client(wid,token,'Client','incorrect-date')
    client=db.add_client(wid,token,'Client')['id']
    with pytest.raises(ValueError):
        db.record_consent(wid,token,client,'unlimited_data','granted','yes')
    with pytest.raises(ValueError):
        db.record_consent(wid,token,client,'view_case','granted','')
