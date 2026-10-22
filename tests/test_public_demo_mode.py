"""APP_ENV=demo: open samples and stateless calculations, everything else closed."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def demo_client(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'demo')
    monkeypatch.delenv('RR_API_ACCESS_KEY', raising=False)
    from renewal.security import access
    # settings.app_env is frozen at import, so patch the helper (same as test_route_auth_gate.py)
    monkeypatch.setattr(access, '_env_name', lambda: 'demo')
    from renewal import main
    with TestClient(main.app) as client:
        yield client


def test_health_paths_are_public(demo_client):
    assert demo_client.get('/health').json() == {'status': 'ok'}
    assert demo_client.get('/api/health').status_code == 200


def test_sample_flow_works_without_a_key(demo_client):
    demo = demo_client.get('/api/demo').json()
    assert demo['mortgage']['lender'] == 'Maple Bank (illustrative)'
    assert demo_client.get('/api/demo/sample.pdf').status_code == 200
    r = demo_client.post('/api/analyze', json={'mortgage': demo['mortgage'], 'offers': demo['offers']})
    assert r.status_code == 200
    body = r.text
    for value in ('3378.66', '3122.52', '13756.07', '74542.72', '60786.65'):
        assert value in body


def test_frontend_shell_is_public(demo_client):
    assert demo_client.get('/').status_code == 200


@pytest.mark.parametrize('method,path', [
    ('post', '/api/cases'),
    ('post', '/api/ratewatch/live/refresh'),
    ('post', '/api/v17/market/refresh'),
])
def test_stateful_and_admin_paths_stay_closed(demo_client, method, path):
    r = getattr(demo_client, method)(path)
    assert r.status_code in (403, 404)


def test_route_table_matches_methods():
    from renewal.security.access import public_demo_allows
    assert public_demo_allows('GET', '/api/demo')
    assert public_demo_allows('HEAD', '/api/demo')
    assert not public_demo_allows('POST', '/api/demo')
    assert not public_demo_allows('GET', '/api/cases')
    assert not public_demo_allows('POST', '/api/broker/workspaces')


def test_live_board_does_not_block_a_fresh_server(tmp_path, monkeypatch):
    import importlib.util
    import threading
    from renewal.ratewatch import live as patched
    # conftest stubs live.board for every test, so load a private copy of the module to test the real function
    spec = importlib.util.spec_from_file_location("renewal.ratewatch._live_copy", patched.__file__)
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    monkeypatch.setattr(live, "BOARD", tmp_path / "live_board.json")
    started = threading.Event()
    release = threading.Event()

    def slow_refresh(lenders=None):
        started.set()
        release.wait(5)
        return {}
    monkeypatch.setattr(live, "refresh", slow_refresh)
    b = live.board(wait=False)
    assert b["refreshed_at"] is None and b["refreshing"] is True and b["banks"] == []
    assert started.wait(5)
    release.set()
