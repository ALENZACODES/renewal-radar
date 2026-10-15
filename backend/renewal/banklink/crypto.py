"""Fernet sealing for bank-link provider handles; production fail-closed key gate."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

from ..leads.identity import Vault

# Reject empty / obvious placeholders even if length looks plausible.
_PLACEHOLDERS = frozenset({
    '',
    'changeme',
    'change-me',
    'secret',
    'password',
    'test',
    'testing',
    'dev',
    'development',
    'local',
    'placeholder',
    'your-key-here',
    'your_key_here',
    'rr_banklink_key',
    'rr-banklink-key',
    'none',
    'null',
    'undefined',
    'example',
    'sample',
    'todo',
    'replace-me',
    'replaceme',
})



class BanklinkKeyError(RuntimeError):
    """RR_BANKLINK_KEY is missing, weak, or invalid for the current environment."""


def configured_banklink_key() -> str:
    return (os.environ.get('RR_BANKLINK_KEY') or '').strip()


def banklink_key_status(key: str | None = None) -> tuple[bool, str]:
    """Return (ok, reason). Rejects empty, placeholder, weak, and non-Fernet keys."""
    raw = configured_banklink_key() if key is None else (key or '').strip()
    if not raw:
        return False, 'missing'
    lowered = raw.lower()
    if lowered in _PLACEHOLDERS:
        return False, 'placeholder'
    if any(p and p in lowered for p in ('changeme', 'placeholder', 'your-key', 'example-key')):
        return False, 'placeholder'
    if len(raw) < 32:
        return False, 'too short (Fernet keys are 44 url-safe base64 characters)'
    try:
        # Validate as a real Fernet key (raises on bad length/padding).
        Fernet(raw.encode('ascii'))
    except Exception:
        return False, 'invalid Fernet key material'
    return True, 'ok'


def is_banklink_key_ready() -> bool:
    ok, _ = banklink_key_status()
    return ok


def require_production_banklink_key() -> None:
    """Fail closed in production when RR_BANKLINK_KEY is missing/weak/placeholder."""
    from ..security.access import is_production

    if not is_production():
        return
    ok, reason = banklink_key_status()
    if not ok:
        raise BanklinkKeyError(
            f'RR_BANKLINK_KEY is required in production ({reason}). '
            'Generate with cryptography.fernet.Fernet.generate_key().'
        )


def _vault() -> Vault | None:
    """Return a Vault when a valid key is configured; None in non-production sandbox only."""
    from ..security.access import is_production

    ok, reason = banklink_key_status()
    if not ok:
        if is_production():
            raise BanklinkKeyError(
                f'RR_BANKLINK_KEY is required in production ({reason})'
            )
        return None
    key = configured_banklink_key()
    return Vault(key.encode('ascii'))


def seal_handle(handle: str) -> str:
    vault = _vault()
    if vault is None:
        # Non-production sandbox stub only.
        return handle
    return vault.seal(handle)


def open_handle(sealed: str) -> str:
    vault = _vault()
    if vault is None:
        return sealed
    try:
        return vault.open(sealed)
    except ValueError:
        # Wrong key / corrupt ciphertext — do not silently return sealed blob as handle.
        from ..security.access import is_production

        if is_production():
            raise BanklinkKeyError('bank-link handle cannot be decrypted with RR_BANKLINK_KEY')
        return sealed


def new_banklink_key() -> str:
    """Helper for ops docs/tests — never log or commit the result."""
    return Fernet.generate_key().decode('ascii')
