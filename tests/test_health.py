from fastapi.testclient import TestClient

from renewal import main
from renewal.observability.health import readiness, run_check


def test_run_check_captures_failure_without_raising():
    def bad():
        raise OSError('secret detail')
    result = run_check('disk', bad)
    assert not result.ok
    assert result.detail == 'OSError'
    assert 'secret' not in result.detail


def test_readiness_degrades_when_any_check_fails():
    report = readiness([('a', lambda: 'ok'), ('b', lambda: 1 / 0)], {'model': False})
    assert report['status'] == 'degraded'
    assert [c['ok'] for c in report['checks']] == [True, False]
    assert report['connectors'] == {'model': False}


def test_live_and_ready_endpoints():
    with TestClient(main.app) as client:
        assert client.get('/api/health/live').json() == {'status': 'alive'}
        ready = client.get('/api/health/ready')
        assert ready.status_code == 200
        body = ready.json()
        assert body['status'] == 'ready'
        assert {c['name'] for c in body['checks']} == {'case_store', 'frontend'}
        assert set(body['connectors']) == {'model', 'search'}
        assert 'api_key' not in ready.text.lower()


def test_ready_returns_503_when_degraded(monkeypatch):
    monkeypatch.setattr(main, '_frontend_check', lambda: (_ for _ in ()).throw(FileNotFoundError()))
    with TestClient(main.app) as client:
        assert client.get('/api/health/ready').status_code == 503
