"""Contact normalisation, duplicate keys and encryption at rest."""
from __future__ import annotations

import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken

EMAIL = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL.match(value) or len(value) > 254:
        raise ValueError('invalid email address')
    local, domain = value.split('@', 1)
    if domain in ('gmail.com', 'googlemail.com'):
        local = local.split('+', 1)[0].replace('.', '')
        domain = 'gmail.com'
    return f'{local}@{domain}'


def normalize_phone(value: str) -> str:
    """Canadian and US numbers to E.164 (+1XXXXXXXXXX)."""
    digits = re.sub(r'\D', '', value)
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in '01' or digits[3] in '01':
        raise ValueError('invalid North American phone number')
    return '+1' + digits


def duplicate_key(secret: bytes, *, email: str | None, phone: str | None, workspace_id: str) -> list[str]:
    """One keyed hash per identifier; a match on any of them is a duplicate for that brokerage."""
    keys = []
    for kind, value in (('email', email), ('phone', phone)):
        if value:
            msg = f'{workspace_id}|{kind}|{value}'.encode()
            keys.append(hmac.new(secret, msg, hashlib.sha256).hexdigest())
    if not keys:
        raise ValueError('an email or phone number is required')
    return keys


class Vault:
    """Symmetric encryption for contact details (Fernet: AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: bytes):
        self._f = Fernet(key)

    @staticmethod
    def new_key() -> bytes:
        return Fernet.generate_key()

    def seal(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError('contact record cannot be decrypted with this key') from exc


def mask_email(email: str) -> str:
    local, domain = email.split('@', 1)
    return (local[0] + '•' * max(1, len(local) - 1)) + '@' + domain


def mask_phone(phone: str) -> str:
    return phone[:2] + '•' * (len(phone) - 6) + phone[-4:]
