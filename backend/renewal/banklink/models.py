"""Types shared by the bank-link adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

D = Decimal


class Provider(str, Enum):
    PLAID = 'plaid'
    FLINKS = 'flinks'


class Scope(str, Enum):
    MORTGAGE_READ = 'mortgage:read'      # balance, rate, maturity, payment
    ACCOUNTS_READ = 'accounts:read'      # account list only, to pick the mortgage


ALLOWED_PURPOSES = frozenset({'renewal_analysis', 'penalty_estimate'})
FORBIDDEN_INPUT_KEYS = frozenset({'password', 'pin', 'username', 'login', 'security_answer',
                                  'card_number', 'otp', 'mfa_code'})


class CredentialRefused(ValueError):
    """Raised whenever a request carries anything that looks like bank credentials."""


@dataclass(frozen=True)
class Consent:
    id: str
    subject: str                 # opaque user or case id, never a name
    provider: Provider
    scopes: frozenset[Scope]
    purpose: str
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.granted_at <= now < self.expires_at


@dataclass(frozen=True)
class LinkSession:
    provider: Provider
    link_token: str              # short-lived token the provider widget needs
    widget_url: str | None
    expires_at: datetime
    sandbox: bool


@dataclass(frozen=True)
class MortgageSnapshot:
    """Only the fields renewal analysis needs; no account numbers or transactions."""
    provider: Provider
    account_ref: str             # provider's opaque id, hashed before storage
    lender_name: str | None
    balance: D | None
    rate_pct: D | None
    rate_type: str | None        # fixed | variable | None when the feed doesn't say
    maturity_date: date | None
    origination_date: date | None
    payment: D | None
    original_principal: D | None
    as_of: date
    missing: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        def s(v: object) -> object:
            if isinstance(v, D):
                return str(v)
            if isinstance(v, date):
                return v.isoformat()
            if isinstance(v, Enum):
                return v.value
            return v
        return {k: (list(v) if isinstance(v, tuple) else s(v)) for k, v in vars(self).items()}


def reject_credentials(payload: dict) -> None:
    """Refuse any payload that carries credential-like keys, at any depth."""
    stack: list[object] = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if str(key).lower().replace('-', '_') in FORBIDDEN_INPUT_KEYS:
                    raise CredentialRefused('Bank credentials are never accepted; use the provider-hosted connection.')
                stack.append(value)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
