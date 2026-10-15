"""Bank-link consent binding, PKCE session state, and link ownership."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from .crypto import seal_handle
from .models import Consent, Provider, Scope
from .service import BankLinkService, ConsentError, _digest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def pkce_challenge(verifier: str) -> str:
    """S256 code_challenge for a code_verifier."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return _b64url(digest)


COOKIE_NAME = 'rr_banklink_nonce'


@dataclass
class ConsentBinding:
    consent_id: str
    workspace_id: str
    case_id: str
    broker_subject: str


@dataclass
class PendingState:
    state: str
    consent_id: str
    code_challenge: str
    cookie_nonce: str | None
    expires_at: datetime
    claimed: bool = False


class BankLinkGateway:
    """HTTP-facing binder around BankLinkService (sandbox in-memory)."""

    def __init__(self, service: BankLinkService, clock: Callable[[], datetime] = _utcnow) -> None:
        self.service = service
        self._clock = clock
        self._bindings: dict[str, ConsentBinding] = {}
        self._states: dict[str, PendingState] = {}
        self._link_owners: dict[str, ConsentBinding] = {}
        self._lock = threading.Lock()

    def bind_consent(
        self,
        *,
        workspace_id: str,
        case_id: str,
        provider: Provider,
        purpose: str,
        days: int = 30,
        payload: dict | None = None,
    ) -> Consent:
        consent = self.service.grant(
            subject=f'case:{case_id}',
            provider=provider,
            scopes={Scope.MORTGAGE_READ},
            purpose=purpose,
            days=days,
            payload=payload,
        )
        binding = ConsentBinding(consent.id, workspace_id, case_id, broker_subject=workspace_id)
        with self._lock:
            self._bindings[consent.id] = binding
        return consent

    def binding(self, consent_id: str) -> ConsentBinding | None:
        with self._lock:
            return self._bindings.get(consent_id)

    def start_session(self, consent_id: str, *, code_challenge: str, bind_cookie: bool = True) -> dict:
        if not code_challenge or len(code_challenge) < 43:
            raise ConsentError('code_challenge required (PKCE S256)')
        session = self.service.start(consent_id)
        state = secrets.token_urlsafe(24)
        cookie_nonce = secrets.token_urlsafe(16) if bind_cookie else None
        pending = PendingState(
            state=state,
            consent_id=consent_id,
            code_challenge=code_challenge,
            cookie_nonce=cookie_nonce,
            expires_at=self._clock() + timedelta(minutes=15),
        )
        with self._lock:
            self._states[state] = pending
        return {
            'provider': session.provider.value,
            'link_token': session.link_token,
            'widget_url': session.widget_url,
            'expires_at': session.expires_at.isoformat(),
            'sandbox': session.sandbox,
            'state': state,
            'cookie_nonce': cookie_nonce,
            'cookie_name': COOKIE_NAME if cookie_nonce else None,
        }

    def complete(
        self,
        *,
        state: str,
        code_verifier: str,
        public_token: str,
        cookie_nonce: str | None,
        payload: dict | None = None,
    ) -> dict:
        from .models import reject_credentials
        # Refuse credential-shaped payloads before claiming state.
        reject_credentials(payload or {})
        with self._lock:
            pending = self._states.get(state)
            if pending is None:
                raise ConsentError('unknown or expired state')
            if pending.claimed:
                raise ConsentError('state already used')
            if pending.expires_at <= self._clock():
                raise ConsentError('state expired')
            expected = pkce_challenge(code_verifier)
            if not hmac.compare_digest(expected, pending.code_challenge):
                raise ConsentError('PKCE verification failed')
            if pending.cookie_nonce is not None:
                if not cookie_nonce or not hmac.compare_digest(pending.cookie_nonce, cookie_nonce):
                    raise ConsentError('browser binding mismatch')
            self._states[state] = replace(pending, claimed=True)
            consent_id = pending.consent_id
            binding = self._bindings.get(consent_id)

        link_id = self.service.complete(consent_id, public_token, payload)
        with self._lock:
            if binding is not None:
                self._link_owners[_digest(link_id)] = binding
        return {
            'link_id': link_id,
            'case_id': binding.case_id if binding else None,
            'workspace_id': binding.workspace_id if binding else None,
        }

    def authorize_link(
        self,
        link_id: str,
        *,
        workspace_id: str | None = None,
        case_id: str | None = None,
    ) -> ConsentBinding:
        with self._lock:
            binding = self._link_owners.get(_digest(link_id))
        if binding is None:
            raise ConsentError('unknown link')
        if workspace_id and binding.workspace_id != workspace_id:
            raise ConsentError('workspace mismatch')
        if case_id and binding.case_id != case_id:
            raise ConsentError('case mismatch')
        return binding

    def revoke(self, consent_id: str) -> bool:
        """Revoke consent and wipe bindings/state/links. Idempotent."""
        try:
            self.service.revoke(consent_id)
        except ConsentError:
            pass  # already gone
        with self._lock:
            self._bindings.pop(consent_id, None)
            for key, b in list(self._link_owners.items()):
                if b.consent_id == consent_id:
                    del self._link_owners[key]
            for key, st in list(self._states.items()):
                if st.consent_id == consent_id:
                    del self._states[key]
        return True
