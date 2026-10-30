import pytest
from fastapi.testclient import TestClient

from renewal.security.rate_limit import Rule, SlidingWindowLimiter


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def make(limit=3, window=10.0):
    clock = Clock()
    return SlidingWindowLimiter((Rule('/api/x', limit, window), Rule('/api/', 100, 60.0)), clock=clock), clock


def test_allows_up_to_limit_then_blocks():
    lim, _ = make()
    decisions = [lim.check('a', '/api/x/1') for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions[:3]] == [2, 1, 0]
    assert decisions[3].retry_after == pytest.approx(10.0)


def test_window_slides():
    lim, clock = make()
    for _ in range(3):
        lim.check('a', '/api/x')
    clock.t += 10.01
    assert lim.check('a', '/api/x').allowed


def test_clients_and_rules_are_isolated():
    lim, _ = make(limit=1)
    assert lim.check('a', '/api/x').allowed
    assert not lim.check('a', '/api/x').allowed
    assert lim.check('b', '/api/x').allowed
    assert lim.check('a', '/api/other').allowed


def test_unmatched_path_is_not_limited():
    lim, _ = make()
    assert lim.check('a', '/assets/app.css') is None


def test_first_matching_rule_wins():
    lim, _ = make()
    assert lim.rule_for('/api/x/y').limit == 3
    assert lim.rule_for('/api/demo').limit == 100


def test_eviction_keeps_store_bounded():
    clock = Clock()
    lim = SlidingWindowLimiter((Rule('/api/', 5, 1.0),), clock=clock, max_keys=10)
    for i in range(50):
        clock.t += 0.01
        lim.check(f'c{i}', '/api/demo')
    assert len(lim._hits) <= 10


@pytest.mark.parametrize('limit,window', [(0, 1.0), (1, 0.0)])
def test_rule_validation(limit, window):
    with pytest.raises(ValueError):
        Rule('/api/', limit, window)


def test_middleware_returns_429_with_retry_after(monkeypatch):
    from renewal import main
    monkeypatch.setattr(main, 'limiter', SlidingWindowLimiter((Rule('/api/demo', 2, 60.0),)))
    client = TestClient(main.app)
    first = client.get('/api/demo')
    assert first.status_code == 200
    assert first.headers['X-RateLimit-Limit'] == '2'
    assert first.headers['X-RateLimit-Remaining'] == '1'
    client.get('/api/demo')
    blocked = client.get('/api/demo')
    assert blocked.status_code == 429
    assert int(blocked.headers['Retry-After']) >= 1
    assert client.get('/api/health').status_code == 200
