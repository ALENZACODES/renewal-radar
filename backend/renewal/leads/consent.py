"""Versioned consent wording and validation for lead handoff (CASL, FSRA, PIPEDA)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConsentText:
    version: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


CONSENT_TEXTS: dict[str, ConsentText] = {
    '2026-10': ConsentText('2026-10', (
        'I ask {brokerage} to contact me about my mortgage renewal by the method I chose. '
        'Renewal Radar will share my name, contact details, renewal date, approximate balance and '
        'the analysis I created, and nothing else. {brokerage} is a licensed mortgage brokerage and may '
        'receive compensation from a lender if I take a mortgage through them; they must disclose it. '
        'I can withdraw this request at any time and my contact details will be deleted.')),
}
CURRENT_VERSION = '2026-10'


class ConsentInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ConsentRecord:
    version: str
    text_digest: str
    agreed_at: datetime
    contact_methods: tuple[str, ...]     # email, phone
    brokerage: str

    def as_dict(self) -> dict:
        return {'version': self.version, 'text_digest': self.text_digest,
                'agreed_at': self.agreed_at.isoformat(), 'contact_methods': list(self.contact_methods),
                'brokerage': self.brokerage}


def validate_consent(*, version: str, text_digest: str, agreed: bool, agreed_at: datetime,
                     contact_methods: list[str], brokerage: str, now: datetime) -> ConsentRecord:
    """Express, specific, current consent only. Pre-ticked or stale forms are rejected."""
    if agreed is not True:
        raise ConsentInvalid('the homeowner must actively agree to be contacted')
    text = CONSENT_TEXTS.get(version)
    if text is None:
        raise ConsentInvalid('unknown consent wording version')
    if version != CURRENT_VERSION:
        raise ConsentInvalid('consent wording is out of date; show the current version')
    if text_digest != text.digest:
        raise ConsentInvalid('consent wording shown does not match the recorded version')
    if agreed_at.tzinfo is None:
        raise ConsentInvalid('agreed_at must include a time zone')
    age = (now - agreed_at).total_seconds()
    if age < -120 or age > 3600:
        raise ConsentInvalid('consent must be submitted within an hour of agreeing')
    methods = tuple(sorted(set(contact_methods)))
    if not methods or not set(methods) <= {'email', 'phone'}:
        raise ConsentInvalid('choose email, phone or both')
    if not brokerage.strip():
        raise ConsentInvalid('the brokerage must be named')
    return ConsentRecord(version, text_digest, agreed_at, methods, brokerage.strip())
