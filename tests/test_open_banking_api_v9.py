from fastapi.testclient import TestClient

from renewal.banking.open_banking import OpenBankingConnector
from renewal.broker.workspace import BrokerWorkspace
from renewal.main import app


def install_isolated_services(monkeypatch, tmp_path):
    import renewal.main as main

    monkeypatch.setattr(main, "broker_workspace", BrokerWorkspace(tmp_path / "broker.sqlite3"))
    monkeypatch.setattr(main, "open_banking", OpenBankingConnector(tmp_path / "banking.sqlite3", state_secret="api-secret"))
    workspace = main.broker_workspace.create_workspace("API Brokerage")
    client = main.broker_workspace.add_client(
        workspace["workspace_id"],
        workspace["access_token"],
        "API Homeowner",
        "2027-02-01",
    )
    return main, workspace, client


def headers(workspace):
    return {"X-Broker-Token": workspace["access_token"]}


def consent(main, workspace, client):
    return main.broker_workspace.record_consent(
        workspace["workspace_id"],
        workspace["access_token"],
        client["id"],
        "bank_data_read",
        "granted",
        "API workflow consent",
    )


def payload_accounts():
    return [
        {
            "provider_account_id": "primary-987654321",
            "display_name": "Primary Chequing",
            "type": "chequing",
            "currency": "CAD",
            "balance": "7000.00",
            "mask": "4321",
        }
    ]


def payload_transactions():
    return [
        {
            "provider_account_id": "primary-987654321",
            "posted_date": "2026-08-05",
            "amount": "-3378.66",
            "description": "Renewal lender mortgage payment account number 987654321",
            "reference": "api-m1",
        },
        {
            "provider_account_id": "primary-987654321",
            "posted_date": "2026-09-05",
            "amount": "-3378.66",
            "description": "Renewal lender mortgage payment account number 987654321",
            "reference": "api-m2",
        },
        {
            "provider_account_id": "primary-987654321",
            "posted_date": "2026-10-05",
            "amount": "-3378.66",
            "description": "Renewal lender mortgage payment account number 987654321",
            "reference": "api-m3",
        },
    ]


def test_institutions_endpoint(monkeypatch, tmp_path):
    install_isolated_services(monkeypatch, tmp_path)
    with TestClient(app) as http:
        response = http.get("/api/v9/banking/institutions")
    assert response.status_code == 200
    assert response.json()["institutions"][0]["sandbox"] is True


def test_api_session_requires_consent(monkeypatch, tmp_path):
    main, workspace, client = install_isolated_services(monkeypatch, tmp_path)
    with TestClient(app) as http:
        response = http.post(
            f"/api/v9/broker/workspaces/{workspace['workspace_id']}/clients/{client['id']}/banking/sessions",
            headers=headers(workspace),
            json={
                "institution_id": "sandbox-maple-bank",
                "redirect_uri": "https://example.test/callback",
                "scopes": ["accounts.basic"],
            },
        )
    assert response.status_code == 403
    assert "consent" in response.json()["detail"].lower()


def test_api_full_banking_workflow(monkeypatch, tmp_path):
    main, workspace, client = install_isolated_services(monkeypatch, tmp_path)
    consent(main, workspace, client)
    wid = workspace["workspace_id"]
    cid = client["id"]
    with TestClient(app) as http:
        session = http.post(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/sessions",
            headers=headers(workspace),
            json={
                "institution_id": "sandbox-maple-bank",
                "redirect_uri": "https://example.test/callback",
                "scopes": ["accounts.basic", "accounts.balance", "transactions.read"],
            },
        )
        assert session.status_code == 201, session.text
        body = session.json()
        assert body["session_id"]
        connection = http.post(
            f"/api/v9/broker/workspaces/{wid}/banking/sessions/{body['session_id']}/exchange",
            headers=headers(workspace),
            json={"authorization_code": "sandbox-approved", "state": body["state"]},
        )
        assert connection.status_code == 200, connection.text
        connection_id = connection.json()["connection_id"]
        imported = http.post(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}/snapshot",
            headers=headers(workspace),
            json={"accounts": payload_accounts(), "transactions": payload_transactions()},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["transactions_imported"] == 3
        accounts = http.get(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/accounts",
            headers=headers(workspace),
        )
        assert accounts.status_code == 200
        assert accounts.json()["accounts"][0]["mask"] == "****4321"
        evidence = http.get(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/payment-evidence?months=12",
            headers=headers(workspace),
        )
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["evidence"][0]["median_amount"] == "3378.66"
        cashflow = http.get(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/cashflow?months=12",
            headers=headers(workspace),
        )
        assert cashflow.status_code == 200
        assert cashflow.json()["expenses"] == "10135.98"
        events = http.get(
            f"/api/v9/broker/workspaces/{wid}/banking/events?client_id={cid}",
            headers=headers(workspace),
        )
        assert events.status_code == 200
        assert len(events.json()["events"]) >= 3
        revoked = http.delete(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}",
            headers=headers(workspace),
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"


def test_api_rejects_bad_snapshot(monkeypatch, tmp_path):
    main, workspace, client = install_isolated_services(monkeypatch, tmp_path)
    consent(main, workspace, client)
    wid = workspace["workspace_id"]
    cid = client["id"]
    with TestClient(app) as http:
        session = http.post(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/sessions",
            headers=headers(workspace),
            json={
                "institution_id": "sandbox-maple-bank",
                "redirect_uri": "https://example.test/callback",
                "scopes": ["accounts.basic", "transactions.read"],
            },
        ).json()
        connection = http.post(
            f"/api/v9/broker/workspaces/{wid}/banking/sessions/{session['session_id']}/exchange",
            headers=headers(workspace),
            json={"authorization_code": "sandbox-approved", "state": session["state"]},
        ).json()
        response = http.post(
            f"/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection['connection_id']}/snapshot",
            headers=headers(workspace),
            json={"accounts": [], "transactions": []},
        )
    assert response.status_code == 422


def test_api_tenant_isolation(monkeypatch, tmp_path):
    main, workspace, client = install_isolated_services(monkeypatch, tmp_path)
    other = main.broker_workspace.create_workspace("Other")
    with TestClient(app) as http:
        response = http.get(
            f"/api/v9/broker/workspaces/{workspace['workspace_id']}/clients/{client['id']}/banking/connections",
            headers=headers(other),
        )
    assert response.status_code == 404

