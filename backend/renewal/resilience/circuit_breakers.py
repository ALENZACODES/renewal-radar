"""Circuit breakers for model and third-party data calls.

Optional connectors (Bank of Canada Valet, lender pages, search, the model
gateway) must never take the deterministic mortgage engine down with them.
A breaker opens after repeated failures, short-circuits calls while open, and
lets a single trial call through after a cool-down.
"""
from __future__ import annotations

import threading
import time
from typing import Awaitable, Callable, Dict, TypeVar

T = TypeVar('T')

CLOSED, OPEN, HALF_OPEN = 'closed', 'open', 'half_open'


class CircuitOpen(RuntimeError):
    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(f'{name} is temporarily unavailable; retry in {retry_after:.0f}s')
        self.name = name
        self.retry_after = retry_after


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, reset_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if failure_threshold < 1:
            raise ValueError('failure_threshold must be at least 1')
        if reset_seconds <= 0:
            raise ValueError('reset_seconds must be positive')
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False
        self.last_error: str | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> str:
        if self._opened_at is None:
            return CLOSED
        if self._clock() - self._opened_at >= self.reset_seconds:
            return HALF_OPEN
        return OPEN

    def _before_call(self) -> None:
        with self._lock:
            state = self._state_unlocked()
            if state == OPEN or (state == HALF_OPEN and self._trial_in_flight):
                retry = 0.0 if self._opened_at is None else max(
                    0.0, self._opened_at + self.reset_seconds - self._clock())
                raise CircuitOpen(self.name, retry)
            if state == HALF_OPEN:
                self._trial_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False
            self.last_error = None

    def record_failure(self, error: BaseException | None = None) -> None:
        with self._lock:
            self._failures += 1
            self._trial_in_flight = False
            self.last_error = type(error).__name__ if error else 'failure'
            if self._opened_at is not None or self._failures >= self.failure_threshold:
                self._opened_at = self._clock()

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        self._before_call()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            self.record_failure(exc)
            raise
        self.record_success()
        return result

    async def acall(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        self._before_call()
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            self.record_failure(exc)
            raise
        self.record_success()
        return result

    def snapshot(self) -> dict:
        with self._lock:
            return {'name': self.name, 'state': self._state_unlocked(),
                    'consecutive_failures': self._failures, 'last_error': self.last_error}


class BreakerRegistry:
    def __init__(self) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, name: str, **options) -> CircuitBreaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, **options)
            return self._breakers[name]

    def snapshot(self) -> list[dict]:
        with self._lock:
            breakers = list(self._breakers.values())
        return [b.snapshot() for b in sorted(breakers, key=lambda b: b.name)]

    def clear(self) -> None:
        with self._lock:
            self._breakers.clear()


registry = BreakerRegistry()
