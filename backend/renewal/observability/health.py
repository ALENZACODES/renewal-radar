"""Liveness and readiness probes.

Liveness answers "is the process up". Readiness runs cheap local checks (case
store reachable, frontend assets present) and reports optional connectors and
circuit-breaker state without ever exposing secret values.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from ..resilience import registry


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    duration_ms: float


def run_check(name: str, fn: Callable[[], object]) -> CheckResult:
    start = time.perf_counter()
    try:
        out = fn()
        ok, detail = True, (out if isinstance(out, str) else 'ok')
    except Exception as exc:  # a failing check must not crash the probe
        ok, detail = False, type(exc).__name__
    return CheckResult(name, ok, detail, round((time.perf_counter() - start) * 1000, 2))


def readiness(checks: Iterable[tuple[str, Callable[[], object]]],
              connectors: dict[str, bool] | None = None) -> dict:
    results = [run_check(n, f) for n, f in checks]
    ready = all(r.ok for r in results)
    return {
        'status': 'ready' if ready else 'degraded',
        'checks': [r.__dict__ for r in results],
        'connectors': dict(connectors or {}),
        'circuit_breakers': registry.snapshot(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
