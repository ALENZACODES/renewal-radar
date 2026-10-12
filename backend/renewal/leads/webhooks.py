"""Signed webhook delivery with retries and a dead-letter state.

Signature header: ``Renewal-Radar-Signature: t=<unix>,v1=<hex hmac-sha256>`` over
``"<t>.<body>"``. Receivers verify with :func:`verify` and reject anything older
than the tolerance, which blocks replays. Each event carries an idempotency id
so a retried delivery can't create a second CRM record.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

HEADER = 'Renewal-Radar-Signature'
TOLERANCE_SECONDS = 300
BACKOFF_SECONDS = (30, 120, 600, 3600, 6 * 3600)   # then dead-letter


def sign(secret: bytes, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret, f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
    return f't={timestamp},v1={mac}'


class SignatureError(ValueError):
    pass


def verify(secret: bytes, body: bytes, header: str, now: int, tolerance: int = TOLERANCE_SECONDS) -> None:
    try:
        parts = dict(item.split('=', 1) for item in header.split(','))
        timestamp = int(parts['t'])
        given = parts['v1']
    except (KeyError, ValueError) as exc:
        raise SignatureError('malformed signature header') from exc
    if abs(now - timestamp) > tolerance:
        raise SignatureError('signature timestamp outside tolerance')
    expected = sign(secret, body, timestamp).split('v1=', 1)[1]
    if not hmac.compare_digest(expected, given):
        raise SignatureError('signature mismatch')


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> int: ...


@dataclass
class Delivery:
    event_id: str
    url: str
    body: bytes
    attempts: int = 0
    next_at: float = 0.0
    status: str = 'pending'          # pending | delivered | dead
    last_error: str | None = None
    history: list[str] = field(default_factory=list)


class Outbox:
    def __init__(self, secret_for: Callable[[str], bytes], transport: Transport,
                 clock: Callable[[], float] = time.time) -> None:
        self._secret_for = secret_for
        self._transport = transport
        self._clock = clock
        self.items: dict[str, Delivery] = {}

    def enqueue(self, event_id: str, url: str, payload: dict) -> Delivery:
        if not url.startswith('https://'):
            raise ValueError('webhook URLs must use https')
        if event_id in self.items:
            return self.items[event_id]          # idempotent
        body = json.dumps({'id': event_id, **payload}, sort_keys=True, separators=(',', ':')).encode()
        d = Delivery(event_id, url, body, next_at=self._clock())
        self.items[event_id] = d
        return d

    def run_due(self) -> list[Delivery]:
        now = self._clock()
        done: list[Delivery] = []
        for d in self.items.values():
            if d.status != 'pending' or d.next_at > now:
                continue
            d.attempts += 1
            ts = int(now)
            headers = {'Content-Type': 'application/json', HEADER: sign(self._secret_for(d.url), d.body, ts),
                       'Idempotency-Key': d.event_id}
            try:
                code = self._transport.post(d.url, d.body, headers)
                ok = 200 <= code < 300
                d.last_error = None if ok else f'HTTP {code}'
                retryable = code >= 500 or code in (408, 429)
            except Exception as exc:              # network failure: retry
                ok, retryable, d.last_error = False, True, type(exc).__name__
            d.history.append(f'attempt {d.attempts}: {"ok" if ok else d.last_error}')
            if ok:
                d.status = 'delivered'
            elif not retryable or d.attempts > len(BACKOFF_SECONDS):
                d.status = 'dead'
            else:
                d.next_at = now + BACKOFF_SECONDS[d.attempts - 1]
            done.append(d)
        return done
