import asyncio

import pytest

from renewal.resilience.circuit_breakers import (CLOSED, HALF_OPEN, OPEN, BreakerRegistry,
                                                 CircuitBreaker, CircuitOpen)


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def boom():
    raise ConnectionError('down')


def trip(breaker, n):
    for _ in range(n):
        with pytest.raises(ConnectionError):
            breaker.call(boom)


def test_opens_after_threshold_and_short_circuits():
    clock = Clock()
    b = CircuitBreaker('boc', failure_threshold=2, reset_seconds=30, clock=clock)
    trip(b, 2)
    assert b.state == OPEN
    with pytest.raises(CircuitOpen) as err:
        b.call(lambda: 'never')
    assert err.value.retry_after == pytest.approx(30)
    assert b.snapshot()['last_error'] == 'ConnectionError'


def test_half_open_trial_success_closes():
    clock = Clock()
    b = CircuitBreaker('boc', failure_threshold=1, reset_seconds=5, clock=clock)
    trip(b, 1)
    clock.t = 5
    assert b.state == HALF_OPEN
    assert b.call(lambda: 42) == 42
    assert b.state == CLOSED
    assert b.snapshot()['consecutive_failures'] == 0


def test_half_open_trial_failure_reopens():
    clock = Clock()
    b = CircuitBreaker('boc', failure_threshold=3, reset_seconds=5, clock=clock)
    trip(b, 3)
    clock.t = 6
    trip(b, 1)
    assert b.state == OPEN


def test_only_one_trial_in_half_open():
    clock = Clock()
    b = CircuitBreaker('lender', failure_threshold=1, reset_seconds=1, clock=clock)
    trip(b, 1)
    clock.t = 2
    b._before_call()  # first trial admitted
    with pytest.raises(CircuitOpen):
        b._before_call()


def test_success_resets_failure_count():
    b = CircuitBreaker('x', failure_threshold=2)
    trip(b, 1)
    b.call(lambda: None)
    trip(b, 1)
    assert b.state == CLOSED


def test_async_call():
    b = CircuitBreaker('model', failure_threshold=1)

    async def ok():
        return 'fine'

    async def bad():
        raise TimeoutError

    assert asyncio.run(b.acall(ok)) == 'fine'
    with pytest.raises(TimeoutError):
        asyncio.run(b.acall(bad))
    with pytest.raises(CircuitOpen):
        asyncio.run(b.acall(ok))


def test_registry_reuses_and_snapshots():
    reg = BreakerRegistry()
    assert reg.get('b') is reg.get('b')
    reg.get('a')
    assert [s['name'] for s in reg.snapshot()] == ['a', 'b']


@pytest.mark.parametrize('kw', [{'failure_threshold': 0}, {'reset_seconds': 0}])
def test_validation(kw):
    with pytest.raises(ValueError):
        CircuitBreaker('x', **kw)
