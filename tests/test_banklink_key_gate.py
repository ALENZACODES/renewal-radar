"""RR_BANKLINK_KEY production fail-closed."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from renewal.banklink import crypto
from renewal.security import access


@pytest.fixture(autouse=True)
def _clear_banklink_key(monkeypatch):
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    yield


def test_rejects_empty_and_placeholders():
    for bad in ('', 'changeme', 'secret', 'test', 'dev', 'placeholder', 'your-key-here', 'none'):
        ok, reason = crypto.banklink_key_status(bad)
        assert not ok, bad
        assert reason in {'missing', 'placeholder', 'too short (Fernet keys are 44 url-safe base64 characters)', 'invalid Fernet key material'} or 'placeholder' in reason or 'short' in reason or 'missing' in reason


def test_rejects_short_and_non_fernet():
    ok, reason = crypto.banklink_key_status('x' * 40)
    assert not ok
    ok, reason = crypto.banklink_key_status('not-a-valid-fernet-key-material-even-if-long-enough==')
    assert not ok


def test_accepts_generated_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('RR_BANKLINK_KEY', key)
    assert crypto.is_banklink_key_ready()
    ok, reason = crypto.banklink_key_status()
    assert ok and reason == 'ok'


def test_production_require_raises_without_key(monkeypatch):
    monkeypatch.setattr(access, '_env_name', lambda: 'production')
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    with pytest.raises(crypto.BanklinkKeyError, match='RR_BANKLINK_KEY'):
        crypto.require_production_banklink_key()


def test_production_require_raises_on_placeholder(monkeypatch):
    monkeypatch.setattr(access, '_env_name', lambda: 'production')
    monkeypatch.setenv('RR_BANKLINK_KEY', 'changeme')
    with pytest.raises(crypto.BanklinkKeyError):
        crypto.require_production_banklink_key()


def test_production_accepts_valid_key(monkeypatch):
    monkeypatch.setattr(access, '_env_name', lambda: 'production')
    monkeypatch.setenv('RR_BANKLINK_KEY', Fernet.generate_key().decode())
    crypto.require_production_banklink_key()  # no raise


def test_seal_fail_closed_in_production(monkeypatch):
    monkeypatch.setattr(access, '_env_name', lambda: 'production')
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    with pytest.raises(crypto.BanklinkKeyError):
        crypto.seal_handle('access-token-sandbox')


def test_seal_plaintext_ok_outside_production(monkeypatch):
    monkeypatch.setattr(access, '_env_name', lambda: 'development')
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    assert crypto.seal_handle('access-token-sandbox') == 'access-token-sandbox'


def test_seal_encrypts_when_key_set(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('RR_BANKLINK_KEY', key)
    sealed = crypto.seal_handle('access-token-sandbox')
    assert sealed != 'access-token-sandbox'
    assert crypto.open_handle(sealed) == 'access-token-sandbox'


def test_complete_remains_public_allowlisted():
    assert access.path_allows_anonymous('/api/v5/banklink/complete')
    assert not access.path_allows_anonymous('/api/v5/banklink/consents')


def test_banklink_routes_503_in_production_without_key(monkeypatch):
    monkeypatch.setenv('RR_ENABLE_BANKLINK_SANDBOX', '1')
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    # Start app outside production so lifespan does not raise; flip env for requests.
    key = 'k' * 32
    monkeypatch.setenv('RR_API_ACCESS_KEY', key)
    from renewal.main import app
    with TestClient(app) as client:
        monkeypatch.setattr(access, '_env_name', lambda: 'production')
        c = client.post(
            '/api/v5/banklink/consents',
            headers={'X-Api-Key': key},
            json={'case_id': 'x', 'workspace_id': 'y', 'provider': 'plaid', 'purpose': 'renewal_analysis'},
        )
        assert c.status_code == 503, c.text
        assert 'RR_BANKLINK_KEY' in c.json()['detail']
        # complete stays allowlisted for API key, but still fail-closed on banklink key
        done = client.post('/api/v5/banklink/complete', json={})
        assert done.status_code == 503
        assert access.path_allows_anonymous('/api/v5/banklink/complete')


def test_lifespan_raises_when_production_missing_key(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setattr(access, '_env_name', lambda: 'production')
    monkeypatch.delenv('RR_BANKLINK_KEY', raising=False)
    # Fresh app lifespan invocation
    from renewal.banklink.crypto import require_production_banklink_key
    with pytest.raises(crypto.BanklinkKeyError):
        require_production_banklink_key()
