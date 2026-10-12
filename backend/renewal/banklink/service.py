"""Consent-gated bank-link flow with minimal retention and an audit trail.

State lives in memory per process (sandbox only). Access handles are stored as
SHA-256 digests mapped to the adapter-side handle so a leaked snapshot can't be
replayed, and snapshots expire after ``retention``.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from .adapters import BankLinkAdapter
from .models import (ALLOWED_PURPOSES, Consent, LinkSession, MortgageSnapshot, Provider, Scope,
                     reject_credentials)

MAX_CONSENT_DAYS = 90


class ConsentError(PermissionError):
    pass


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class _Link:
    consent_id: str
    provider: Provider
    handle: str
    snapshots: list[MortgageSnapshot] = field(default_factory=list)
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class AuditEvent:
    at: datetime
    consent_id: str
    action: str
    detail: str


class BankLinkService:
    def __init__(self, adapters: dict[Provider, BankLinkAdapter], *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 retention: timedelta = timedelta(days=30)) -> None:
        self._adapters = adapters
        self._clock = clock
        self._retention = retention
        self._consents: dict[str, Consent] = {}
        self._links: dict[str, _Link] = {}            # digest(link id) -> link
        self._audit: list[AuditEvent] = []
        self._lock = threading.Lock()

    # consent -----------------------------------------------------------------
    def grant(self, subject: str, provider: Provider, scopes: set[Scope], purpose: str,
              days: int = 30, payload: dict | None = None) -> Consent:
        reject_credentials(payload or {})
        if provider not in self._adapters:
            raise ConsentError(f'{provider.value} is not enabled')
        if purpose not in ALLOWED_PURPOSES:
            raise ConsentError(f'purpose must be one of {sorted(ALLOWED_PURPOSES)}')
        if Scope.MORTGAGE_READ not in scopes:
            raise ConsentError('mortgage:read scope is required')
        if not 1 <= days <= MAX_CONSENT_DAYS:
            raise ConsentError(f'consent may last 1 to {MAX_CONSENT_DAYS} days')
        now = self._clock()
        consent = Consent(secrets.token_urlsafe(18), subject, provider, frozenset(scopes), purpose,
                          now, now + timedelta(days=days))
        with self._lock:
            self._consents[consent.id] = consent
            self._log(consent.id, 'consent_granted', f'{provider.value} {sorted(s.value for s in scopes)} {purpose}')
        return consent

    def _active(self, consent_id: str) -> Consent:
        consent = self._consents.get(consent_id)
        if consent is None or not consent.active(self._clock()):
            raise ConsentError('consent is missing, expired or revoked')
        return consent

    def revoke(self, consent_id: str) -> None:
        with self._lock:
            consent = self._consents.get(consent_id)
            if consent is None:
                raise ConsentError('unknown consent')
            for key, link in list(self._links.items()):
                if link.consent_id == consent_id:
                    self._adapters[link.provider].revoke(link.handle)
                    del self._links[key]
            self._consents[consent_id] = replace(consent, revoked_at=self._clock())
            self._log(consent_id, 'consent_revoked', 'provider access removed and snapshots deleted')

    # linking -----------------------------------------------------------------
    def start(self, consent_id: str) -> LinkSession:
        consent = self._active(consent_id)
        session = self._adapters[consent.provider].start(consent.subject)
        self._log(consent_id, 'link_started', consent.provider.value)
        return session

    def complete(self, consent_id: str, public_token: str, payload: dict | None = None) -> str:
        reject_credentials(payload or {})
        consent = self._active(consent_id)
        handle = self._adapters[consent.provider].exchange(public_token)
        link_id = secrets.token_urlsafe(24)
        with self._lock:
            self._links[_digest(link_id)] = _Link(consent_id, consent.provider, handle)
            self._log(consent_id, 'link_completed', consent.provider.value)
        return link_id

    def mortgages(self, link_id: str, refresh: bool = False) -> list[MortgageSnapshot]:
        link = self._links.get(_digest(link_id))
        if link is None:
            raise ConsentError('unknown link')
        self._active(link.consent_id)
        now = self._clock()
        if refresh or link.fetched_at is None or now - link.fetched_at > self._retention:
            snaps = self._adapters[link.provider].mortgages(link.handle, now.date())
            link.snapshots = [replace(s, account_ref=_digest(s.account_ref)[:16]) for s in snaps]
            link.fetched_at = now
            self._log(link.consent_id, 'mortgages_fetched', f'{len(snaps)} mortgage account(s)')
        return list(link.snapshots)

    def purge_expired(self) -> int:
        """Drop snapshots past retention and links whose consent lapsed."""
        now = self._clock()
        removed = 0
        with self._lock:
            for key, link in list(self._links.items()):
                consent = self._consents.get(link.consent_id)
                if consent is None or not consent.active(now):
                    self._adapters[link.provider].revoke(link.handle)
                    del self._links[key]
                    removed += 1
                elif link.fetched_at and now - link.fetched_at > self._retention:
                    link.snapshots, link.fetched_at = [], None
                    removed += 1
        return removed

    # audit -------------------------------------------------------------------
    def _log(self, consent_id: str, action: str, detail: str) -> None:
        self._audit.append(AuditEvent(self._clock(), consent_id, action, detail))

    def audit(self, consent_id: str) -> list[dict]:
        return [{'at': e.at.isoformat(), 'action': e.action, 'detail': e.detail}
                for e in self._audit if e.consent_id == consent_id]


def to_renewal_inputs(snapshot: MortgageSnapshot) -> dict:
    """Pre-fill values for the renewal form; the user still confirms each one."""
    out: dict = {'source': f'{snapshot.provider.value} (linked account)', 'confirm_required': True}
    if snapshot.balance is not None:
        out['balance'] = str(snapshot.balance)
    if snapshot.rate_pct is not None:
        out['current_rate'] = str(snapshot.rate_pct)
    if snapshot.rate_type:
        out['rate_type'] = snapshot.rate_type
    if snapshot.maturity_date:
        out['maturity_date'] = snapshot.maturity_date.isoformat()
    if snapshot.payment is not None:
        out['payment'] = str(snapshot.payment)
    out['ask_user_for'] = list(snapshot.missing)
    return out


