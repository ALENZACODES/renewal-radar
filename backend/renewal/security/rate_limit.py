"""In-process sliding-window rate limiting for the public API.

The limiter is deliberately small and dependency-free so the local demo and the
test suite behave the same way. A multi-instance deployment should swap the
store for a shared one (for example Redis) behind the same interface.

Callers must pass a trusted client identifier. Behind a reverse proxy this is
the verified remote address from the proxy, never an unverified X-Forwarded-For.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict


@dataclass(frozen=True)
class Rule:
    """``limit`` requests per ``window_seconds`` for paths starting with ``prefix``."""
    prefix: str
    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError('limit must be at least 1')
        if self.window_seconds <= 0:
            raise ValueError('window_seconds must be positive')


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float


# Expensive or abuse-prone routes get tighter budgets; first matching rule wins.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule('/api/documents/extract', 20, 60.0),
    Rule('/api/agent/', 20, 60.0),
    Rule('/api/report/pdf', 30, 60.0),
    Rule('/api/market/', 30, 60.0),
    Rule('/api/', 300, 60.0),
)


class SlidingWindowLimiter:
    def __init__(self, rules: tuple[Rule, ...] = DEFAULT_RULES,
                 clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 50_000) -> None:
        self.rules = tuple(rules)
        self._clock = clock
        self._max_keys = max_keys
        self._hits: Dict[tuple[str, str], Deque[float]] = {}
        self._lock = threading.Lock()

    def rule_for(self, path: str) -> Rule | None:
        for rule in self.rules:
            if path.startswith(rule.prefix):
                return rule
        return None

    def check(self, client: str, path: str) -> Decision | None:
        """Record one request and return the decision, or ``None`` if no rule applies."""
        rule = self.rule_for(path)
        if rule is None:
            return None
        now = self._clock()
        key = (client, rule.prefix)
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self._max_keys:
                    self._evict(now)
                hits = self._hits[key] = deque()
            cutoff = now - rule.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= rule.limit:
                retry = max(0.0, hits[0] + rule.window_seconds - now)
                return Decision(False, rule.limit, 0, retry)
            hits.append(now)
            return Decision(True, rule.limit, rule.limit - len(hits), 0.0)

    def _evict(self, now: float) -> None:
        stale = [k for k, q in self._hits.items()
                 if not q or q[-1] <= now - self._window(k[1])]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:
            # Still full: drop the least recently used keys.
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: len(self._hits) // 10 or 1]:
                del self._hits[k]

    def _window(self, prefix: str) -> float:
        for rule in self.rules:
            if rule.prefix == prefix:
                return rule.window_seconds
        return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
