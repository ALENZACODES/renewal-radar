import pytest
from fastapi.testclient import TestClient
from renewal.main import app, broker_workspace, renewal_queue


def test_renewal_api_workflow(monkeypatch, tmp_path):
    from renewal.broker.workspace import BrokerWorkspace
    from renewal.broker.renewal_queue import RenewalQueue
    import renewal.main as main
    monkeypatch.setattr(main, 'broker_workspace', BrokerWorkspace(tmp_path/'brokers.sqlite3'))
    monkeypatch.setattr(main, 'renewal_queue', RenewalQueue(tmp_path/'queue.sqlite3'))
    workspace=main.broker_workspace.create_workspace('Sample brokerage')
    wid=workspace['workspace_id']
    headers={'X-Broker-Token':workspace['access_token']}
    client=main.broker_workspace.add_client(wid, workspace['access_token'], 'Sample homeowner',
                                            '2026-10-28')
    with TestClient(app) as http:
        denied=http.post(f'/api/v6/broker/workspaces/{wid}/renewal-tasks/synchronize')
        assert denied.status_code==404
        result=http.post(f'/api/v6/broker/workspaces/{wid}/renewal-tasks/synchronize',headers=headers)
        assert result.status_code==200
        tasks=http.get(f'/api/v6/broker/workspaces/{wid}/renewal-tasks',headers=headers)
        assert tasks.status_code==200
        assert len(tasks.json()['tasks'])==1
        assert tasks.json()['tasks'][0]['contact_consent_current'] is False
        task=tasks.json()['tasks'][0]['id']
        main.broker_workspace.record_consent(wid,workspace['access_token'],client['id'],
                                             'contact_homeowner','granted','Explicit phone consent')
        tasks=http.get(f'/api/v6/broker/workspaces/{wid}/renewal-tasks',headers=headers)
        assert tasks.json()['tasks'][0]['contact_consent_current'] is True
        moved=http.put(f'/api/v6/broker/workspaces/{wid}/renewal-tasks/{task}',headers=headers,
                       json={'state':'completed','note':'Reviewed renewal options'})
        assert moved.status_code==200
        assert moved.json()['state']=='completed'
        audit=http.get(f'/api/v6/broker/workspaces/{wid}/renewal-tasks/{task}/audit',headers=headers)
        assert len(audit.json()['events'])==2
        assert http.get(f'/api/v6/broker/workspaces/{wid}/renewal-tasks',headers=headers).json()['tasks']==[]


def test_renewal_api_invalid_state(monkeypatch,tmp_path):
    from renewal.broker.workspace import BrokerWorkspace
    from renewal.broker.renewal_queue import RenewalQueue
    import renewal.main as main
    monkeypatch.setattr(main,'broker_workspace',BrokerWorkspace(tmp_path/'b.sqlite3'))
    monkeypatch.setattr(main,'renewal_queue',RenewalQueue(tmp_path/'q.sqlite3'))
    workspace=main.broker_workspace.create_workspace('B')
    wid=workspace['workspace_id']
    headers={'X-Broker-Token':workspace['access_token']}
    with TestClient(app) as http:
        response=http.get(f'/api/v6/broker/workspaces/{wid}/renewal-tasks?state=made-up',
                          headers=headers)
        assert response.status_code==422
