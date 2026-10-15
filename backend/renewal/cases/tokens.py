"""Scoped case access tokens (hash-at-rest, TTL, allowlisted scopes).

Broker workspace tokens authorize minting. Case tokens are capability credentials
for borrower/session flows (e.g. banklink:connect). Email OTP binding is TODO.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

ALLOWED_SCOPES = frozenset({
    'case:read',
    'case:write',
    'case:share',
    'banklink:connect',
    'banklink:read',
})

MAX_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_TTL_SECONDS = 3600
# Simple per-case mint rate limit (in-process; production should use shared store).
_MINT_WINDOW = 60.0
_MINT_LIMIT = 10


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CaseTokenRecord:
    token_hash: str
    case_id: str
    workspace_id: str
    scopes: frozenset[str]
    expires_at: datetime
    created_at: datetime
    revoked: bool = False


class CaseTokenStore:
    """In-SQLAlchemy companion would be ideal; start with process memory + optional SQL.

    For the demo SQLite store we keep an in-process map keyed by token hash, and
    also persist via the cases store helpers when available.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, CaseTokenRecord] = {}
        self._mints: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._audit: list[dict] = []

    def _rate_limit(self, case_id: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._mints.setdefault(case_id, [])
            hits[:] = [t for t in hits if now - t < _MINT_WINDOW]
            if len(hits) >= _MINT_LIMIT:
                raise PermissionError('case token mint rate limit exceeded')
            hits.append(now)

    def mint(
        self,
        *,
        case_id: str,
        workspace_id: str,
        scopes: Iterable[str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict:
        scope_set = frozenset(scopes)
        if not scope_set or not scope_set <= ALLOWED_SCOPES:
            raise ValueError(f'scopes must be a non-empty subset of {sorted(ALLOWED_SCOPES)}')
        if not 60 <= int(ttl_seconds) <= MAX_TTL_SECONDS:
            raise ValueError(f'ttl_seconds must be between 60 and {MAX_TTL_SECONDS}')
        self._rate_limit(case_id)
        raw = secrets.token_urlsafe(32)
        now = _utcnow()
        rec = CaseTokenRecord(
            token_hash=_sha(raw),
            case_id=case_id,
            workspace_id=workspace_id,
            scopes=scope_set,
            expires_at=now + timedelta(seconds=int(ttl_seconds)),
            created_at=now,
        )
        with self._lock:
            self._tokens[rec.token_hash] = rec
            self._audit.append({
                'at': now.isoformat(),
                'action': 'case_token_minted',
                'case_id': case_id,
                'workspace_id': workspace_id,
                'scopes': sorted(scope_set),
                'expires_at': rec.expires_at.isoformat(),
            })
        return {
            'token': raw,
            'case_id': case_id,
            'scopes': sorted(scope_set),
            'expires_at': rec.expires_at.isoformat(),
            # plaintext returned once; only hash is retained
        }

    def verify(
        self,
        case_id: str,
        token: str | None,
        *,
        required: str | Iterable[str] | None = None,
    ) -> CaseTokenRecord | None:
        if not token:
            return None
        digest = _sha(token)
        with self._lock:
            rec = self._tokens.get(digest)
            if rec is None or rec.revoked or rec.case_id != case_id:
                return None
            if rec.expires_at <= _utcnow():
                return None
            need = set()
            if isinstance(required, str):
                need = {required}
            elif required:
                need = set(required)
            if need and not need <= set(rec.scopes):
                return None
            return rec

    def revoke(self, case_id: str, token: str | None) -> bool:
        if not token:
            return False
        digest = _sha(token)
        with self._lock:
            rec = self._tokens.get(digest)
            if rec is None or rec.case_id != case_id:
                return False
            if rec.revoked:
                return True  # idempotent
            self._tokens[digest] = CaseTokenRecord(
                token_hash=rec.token_hash,
                case_id=rec.case_id,
                workspace_id=rec.workspace_id,
                scopes=rec.scopes,
                expires_at=rec.expires_at,
                created_at=rec.created_at,
                revoked=True,
            )
            self._audit.append({
                'at': _utcnow().isoformat(),
                'action': 'case_token_revoked',
                'case_id': case_id,
            })
            return True

    def audit(self, case_id: str | None = None) -> list[dict]:
        with self._lock:
            if case_id is None:
                return list(self._audit)
            return [e for e in self._audit if e.get('case_id') == case_id]


case_tokens = CaseTokenStore()
