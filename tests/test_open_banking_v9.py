from datetime import datetime, timedelta, timezone

import pytest

from renewal.banking.open_banking import (
    BankingError,
    BankingSessionExpired,
    ConsentRequired,
    OpenBankingConnector,
    canonical_scopes,
    classify_transaction,
    create_signed_state,
    decode_signed_state,
    mask_identifier,
    normalize_account,
    normalize_transaction,
    redact_description,
    validate_redirect_uri,
)
from renewal.broker.workspace import BrokerWorkspace


def workspace_with_client(tmp_path, consent=True):
    broker = BrokerWorkspace(tmp_path / "broker.sqlite3")
    banking = OpenBankingConnector(tmp_path / "banking.sqlite3", state_secret="test-secret")
    workspace = broker.create_workspace("Brokerage")
    client = broker.add_client(
        workspace["workspace_id"],
        workspace["access_token"],
        "Homeowner",
        "2027-03-01",
    )
    if consent:
        broker.record_consent(
            workspace["workspace_id"],
            workspace["access_token"],
            client["id"],
            "bank_data_read",
            "granted",
            "Borrower accepted bank-data read consent in test fixture",
        )
    return broker, banking, workspace, client


def create_connection(tmp_path):
    broker, banking, workspace, client = workspace_with_client(tmp_path)
    session = banking.create_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        institution_id="sandbox-maple-bank",
        redirect_uri="https://example.test/callback",
        scopes=["transactions.read", "accounts.basic", "accounts.balance"],
        broker_workspace=broker,
    )
    connection = banking.exchange_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        session_id=session["session_id"],
        authorization_code="sandbox-approved",
        state=session["state"],
        broker_workspace=broker,
    )
    return broker, banking, workspace, client, session, connection


def sample_accounts():
    return [
        {
            "provider_account_id": "chequing-123456789",
            "display_name": "Everyday Chequing",
            "type": "chequing",
            "currency": "CAD",
            "balance": "2450.10",
            "mask": "6789",
        }
    ]


def sample_transactions():
    return [
        {
            "provider_account_id": "chequing-123456789",
            "posted_date": "2026-07-01",
            "amount": "-3122.52",
            "description": "MAPLE BANK MORTGAGE PAYMENT loan number 123456789",
            "reference": "m1",
        },
        {
            "provider_account_id": "chequing-123456789",
            "posted_date": "2026-08-01",
            "amount": "-3122.52",
            "description": "MAPLE BANK MORTGAGE PAYMENT loan number 123456789",
            "reference": "m2",
        },
        {
            "provider_account_id": "chequing-123456789",
            "posted_date": "2026-09-01",
            "amount": "-3122.52",
            "description": "MAPLE BANK MORTGAGE PAYMENT loan number 123456789",
            "reference": "m3",
        },
        {
            "provider_account_id": "chequing-123456789",
            "posted_date": "2026-09-15",
            "amount": "6400.00",
            "description": "Payroll Direct Deposit",
            "reference": "pay1",
        },
    ]


def test_canonical_scopes_are_sorted_unique_and_strict():
    assert canonical_scopes(["transactions.read", "accounts.basic", "transactions.read"]) == (
        "accounts.basic",
        "transactions.read",
    )
    with pytest.raises(BankingError):
        canonical_scopes(["transactions.write"])
    with pytest.raises(BankingError):
        canonical_scopes([])


def test_redirect_uri_rules():
    assert validate_redirect_uri("https://example.test/callback").startswith("https://")
    assert validate_redirect_uri("http://localhost:8000/callback").startswith("http://")
    with pytest.raises(BankingError):
        validate_redirect_uri("http://example.test/callback")
    with pytest.raises(BankingError):
        validate_redirect_uri("javascript:alert(1)")
    with pytest.raises(BankingError):
        validate_redirect_uri("https://user:pass@example.test/callback")


def test_signed_state_detects_tampering():
    state = create_signed_state("secret", "sid", "wid", "cid", "nonce")
    assert decode_signed_state("secret", state)["sid"] == "sid"
    tampered = state[:-2] + "AA"
    with pytest.raises(BankingError):
        decode_signed_state("secret", tampered)
    with pytest.raises(BankingError):
        decode_signed_state("wrong", state)


def test_redaction_masks_identifiers():
    text = "Loan number ABCD1234567 phone 416-555-1212 test@example.com SIN 123-456-789"
    redacted = redact_description(text)
    assert "ABCD1234567" not in redacted
    assert "416-555-1212" not in redacted
    assert "test@example.com" not in redacted
    assert "123-456-789" not in redacted
    assert mask_identifier("123456789") == "****6789"


def test_transaction_classification():
    assert classify_transaction("Mortgage payment", -100) == "mortgage_payment"
    assert classify_transaction("Payroll direct deposit", 2000) == "income"
    assert classify_transaction("Municipal property tax", -500) == "property_tax"
    assert classify_transaction("Insurance premium", -25) == "insurance"
    assert classify_transaction("Coffee shop", -7) == "expense"
    assert classify_transaction("Refund", 7) == "deposit"


def test_normalize_account_and_transaction():
    account = normalize_account(sample_accounts()[0], "sandbox-maple-bank", "2026-10-12T12:00:00+00:00")
    tx = normalize_transaction(sample_transactions()[0], {"chequing-123456789": account})
    assert account.mask == "****6789"
    assert account.balance == account.balance.quantize(account.balance)
    assert tx.category == "mortgage_payment"
    assert "[9-digit-id]" in tx.description
    with pytest.raises(BankingError):
        normalize_account({"provider_account_id": "x", "currency": "USD"}, "bank", "2026-01-01T00:00:00+00:00")
    with pytest.raises(BankingError):
        normalize_transaction({"provider_account_id": "missing", "amount": "1", "posted_date": "2026-01-01", "description": "x"}, {})


def test_session_requires_bank_data_consent(tmp_path):
    broker, banking, workspace, client = workspace_with_client(tmp_path, consent=False)
    with pytest.raises(ConsentRequired):
        banking.create_session(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            institution_id="sandbox-maple-bank",
            redirect_uri="https://example.test/callback",
            scopes=["accounts.basic"],
            broker_workspace=broker,
        )


def test_create_session_returns_sandbox_authorization_url(tmp_path):
    broker, banking, workspace, client = workspace_with_client(tmp_path)
    result = banking.create_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        institution_id="sandbox-maple-bank",
        redirect_uri="https://example.test/callback",
        scopes=["accounts.basic", "transactions.read"],
        broker_workspace=broker,
    )
    assert "state=" in result["authorization_url"]
    assert result["state"] in result["authorization_url"]
    assert "code_challenge=" in result["authorization_url"]
    assert result["raw_tokens_returned"] is False if "raw_tokens_returned" in result else True
    assert result["notice"].startswith("Sandbox")


def test_exchange_session_returns_connection_without_raw_tokens(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    assert connection["status"] == "active"
    assert connection["raw_tokens_returned"] is False
    assert "access" not in str(connection).lower()
    listed = banking.list_connections(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        broker_workspace=broker,
    )
    assert listed[0]["connection_id"] == connection["connection_id"]


def test_exchange_rejects_bad_code_and_reuse(tmp_path):
    broker, banking, workspace, client = workspace_with_client(tmp_path)
    session = banking.create_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        institution_id="sandbox-maple-bank",
        redirect_uri="https://example.test/callback",
        scopes=["accounts.basic"],
        broker_workspace=broker,
    )
    with pytest.raises(BankingError):
        banking.exchange_session(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            session_id=session["session_id"],
            authorization_code="real-bank-code",
            state=session["state"],
            broker_workspace=broker,
        )
    connection = banking.exchange_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        session_id=session["session_id"],
        authorization_code="sandbox-good",
        state=session["state"],
        broker_workspace=broker,
    )
    assert connection["status"] == "active"
    with pytest.raises(BankingError):
        banking.exchange_session(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            session_id=session["session_id"],
            authorization_code="sandbox-again",
            state=session["state"],
            broker_workspace=broker,
        )


def test_exchange_marks_expired_session(tmp_path):
    broker, banking, workspace, client = workspace_with_client(tmp_path)
    session = banking.create_session(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        institution_id="sandbox-maple-bank",
        redirect_uri="https://example.test/callback",
        scopes=["accounts.basic"],
        broker_workspace=broker,
        expires_minutes=1,
    )
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with banking._db() as db:
        db.execute("UPDATE banking_sessions SET expires_at=? WHERE id=?", (old, session["session_id"]))
    with pytest.raises(BankingSessionExpired):
        banking.exchange_session(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            session_id=session["session_id"],
            authorization_code="sandbox-late",
            state=session["state"],
            broker_workspace=broker,
        )


def test_import_snapshot_and_idempotent_transactions(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    imported = banking.import_snapshot(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        connection_id=connection["connection_id"],
        accounts=sample_accounts(),
        transactions=sample_transactions(),
        broker_workspace=broker,
    )
    again = banking.import_snapshot(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        connection_id=connection["connection_id"],
        accounts=sample_accounts(),
        transactions=sample_transactions(),
        broker_workspace=broker,
    )
    assert imported["accounts_imported"] == 1
    assert imported["transactions_imported"] == 4
    assert again["transactions_imported"] == 0
    accounts = banking.accounts(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        broker_workspace=broker,
    )
    assert accounts[0]["mask"] == "****6789"


def test_import_rechecks_current_consent(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    broker.record_consent(
        workspace["workspace_id"],
        workspace["access_token"],
        client["id"],
        "bank_data_read",
        "revoked",
        "Customer withdrew bank data consent",
    )
    with pytest.raises(ConsentRequired):
        banking.import_snapshot(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            connection_id=connection["connection_id"],
            accounts=sample_accounts(),
            transactions=[],
            broker_workspace=broker,
        )


def test_revoke_connection_blocks_future_import(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    revoked = banking.revoke_connection(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        connection_id=connection["connection_id"],
        broker_workspace=broker,
    )
    assert revoked["status"] == "revoked"
    with pytest.raises(BankingError):
        banking.import_snapshot(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            connection_id=connection["connection_id"],
            accounts=sample_accounts(),
            transactions=[],
            broker_workspace=broker,
        )


def test_payment_evidence_and_cashflow(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    banking.import_snapshot(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        connection_id=connection["connection_id"],
        accounts=sample_accounts(),
        transactions=sample_transactions(),
        broker_workspace=broker,
    )
    evidence = banking.payment_evidence(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        broker_workspace=broker,
        months=12,
    )
    assert evidence["evidence"][0]["transaction_count"] == 3
    assert evidence["evidence"][0]["median_amount"] == "3122.52"
    assert evidence["evidence"][0]["confidence"] == "high"
    cashflow = banking.cashflow_summary(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        broker_workspace=broker,
        months=12,
    )
    assert cashflow["income"] == "6400.00"
    assert cashflow["expenses"] == "9367.56"
    assert cashflow["categories"]["mortgage_payment"] == "-9367.56"


def test_tenant_isolation(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    other = broker.create_workspace("Other")
    with pytest.raises(Exception):
        banking.list_connections(
            workspace_id=workspace["workspace_id"],
            broker_token=other["access_token"],
            client_id=client["id"],
            broker_workspace=broker,
        )


def test_limits_and_unknowns(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    with pytest.raises(BankingError):
        banking.create_session(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            institution_id="missing-bank",
            redirect_uri="https://example.test/callback",
            scopes=["accounts.basic"],
            broker_workspace=broker,
        )
    with pytest.raises(BankingError):
        banking.import_snapshot(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            connection_id=connection["connection_id"],
            accounts=[],
            transactions=[],
            broker_workspace=broker,
        )
    too_many = [{"provider_account_id": f"a{i}", "balance": "1"} for i in range(21)]
    with pytest.raises(BankingError):
        banking.import_snapshot(
            workspace_id=workspace["workspace_id"],
            broker_token=workspace["access_token"],
            client_id=client["id"],
            connection_id=connection["connection_id"],
            accounts=too_many,
            transactions=[],
            broker_workspace=broker,
        )


def test_event_log_records_major_steps(tmp_path):
    broker, banking, workspace, client, session, connection = create_connection(tmp_path)
    banking.import_snapshot(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        client_id=client["id"],
        connection_id=connection["connection_id"],
        accounts=sample_accounts(),
        transactions=sample_transactions(),
        broker_workspace=broker,
    )
    events = banking.events(
        workspace_id=workspace["workspace_id"],
        broker_token=workspace["access_token"],
        broker_workspace=broker,
        client_id=client["id"],
    )
    actions = [event["action"] for event in events]
    assert "banking_snapshot_imported" in actions
    assert "banking_connection_active" in actions
    assert "banking_session_created" in actions
