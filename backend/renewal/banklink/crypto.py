"""Optional Fernet sealing for bank-link provider handles at rest."""
from __future__ import annotations

import os

from ..leads.identity import Vault


def _vault() -> Vault | None:
    """RR_BANKLINK_KEY: Fernet url-safe base64 key. None => plaintext (sandbox stub)."""
    key = os.environ.get('RR_BANKLINK_KEY', '')
    if not key:
        return None
    try:
        return Vault(key.encode() if isinstance(key, str) else key)
    except Exception:
        # TODO: fail closed when APP_ENV=production
        return None


def seal_handle(handle: str) -> str:
    vault = _vault()
    if vault is None:
        # TODO: require RR_BANKLINK_KEY in production
        return handle
    return vault.seal(handle)


def open_handle(sealed: str) -> str:
    vault = _vault()
    if vault is None:
        return sealed
    try:
        return vault.open(sealed)
    except ValueError:
        return sealed
