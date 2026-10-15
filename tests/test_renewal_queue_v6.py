from datetime import date, timedelta
import pytest
from renewal.broker.renewal_queue import RenewalQueue, assess_renewal, threshold_for


@pytest.mark.parametrize('days,expected', [(-12,0),(0,0),(1,7),(7,7),(8,14),
    (15,30),(31,60),(61,90),(91,120),(121,180),(181,None)])
def test_threshold(days,expected):
    assert threshold_for(days)==expected


def test_signal_consent_and_priority():
    ref=date(2026,10,12)
    future=(ref+timedelta(days=10)).isoformat()
    warning=assess_renewal('a',future,ref.isoformat(),False)
    assert warning.requires_consent and warning.priority=='critical'
    assert not assess_renewal('a',future,ref.isoformat(),True).requires_consent


def test_overdue_signal():
    signal=assess_renewal('a','2026-10-01','2026-10-12',True)
    assert signal.priority=='overdue'
    assert signal.days_remaining==-11


def test_invalid_calendar_dates():
    with pytest.raises(ValueError):
        assess_renewal('a','2026-02-30','2026-10-12',True)


def test_idempotency_and_tenant_isolation(tmp_path):
    queue=RenewalQueue(tmp_path/'queue.sqlite3')
    clients=[{'client_id':'c1','renewal_date':'2026-10-28','contact_consent':False}]
    first=queue.synchronize('broker1',clients,as_of='2026-10-12')
    second=queue.synchronize('broker1',clients,as_of='2026-10-12')
    other=queue.synchronize('broker2',clients,as_of='2026-10-12')
    assert first['inserted']==1 and second['inserted']==0 and other['inserted']==1
    assert len(queue.list_tasks('broker1'))==1
    assert len(queue.list_tasks('broker2'))==1
    assert queue.list_tasks('broker1')[0]['id']!=queue.list_tasks('broker2')[0]['id']


def test_lifecycle_and_audit(tmp_path):
    queue=RenewalQueue(tmp_path/'queue.sqlite3')
    queue.synchronize('a',[{'client_id':'c','renewal_date':'2026-10-17'}],as_of='2026-10-12')
    item=queue.list_tasks('a')[0]
    assert queue.change_state('b',item['id'],'completed') is None
    done=queue.change_state('a',item['id'],'completed','Spoke to client')
    assert done['state']=='completed'
    assert queue.list_tasks('a')==[]
    assert len(queue.events('a',item['id']))==2
    assert queue.events('b',item['id'])==[]
    assert queue.change_state('a',item['id'],'completed')==done
    assert len(queue.events('a',item['id']))==2


def test_error_collect_no_partial_invalid(tmp_path):
    queue=RenewalQueue(tmp_path/'queue.sqlite3')
    output=queue.synchronize('a',[{'client_id':'ok','renewal_date':'2026-10-17'},
                  {'client_id':'bad','renewal_date':'2026-02-30'},
                  {'client_id':'later','renewal_date':'2028-11-04'}],as_of='2026-10-12')
    assert output['inserted']==1 and len(output['errors'])==1
    assert output['notifications_sent']==0


def test_limits_and_states(tmp_path):
    queue=RenewalQueue(tmp_path/'queue.sqlite3')
    with pytest.raises(ValueError):
        queue.list_tasks('a',state='unknown')
    with pytest.raises(ValueError):
        queue.list_tasks('a',limit=1001)
    with pytest.raises(ValueError):
        queue.change_state('a','x','queued')
