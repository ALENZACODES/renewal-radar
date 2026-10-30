"""Consent-gated banking connectivity foundation.

This module deliberately implements a local/sandbox open-banking boundary rather
than a live bank connector. It gives the application durable consent sessions,
provider metadata, token-vault bookkeeping, normalized account and transaction
snapshots, revocation, and mortgage-payment evidence extraction without sending
data to a financial institution or storing raw access tokens.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from threading import RLock
from urllib.parse import urlencode, urlparse

_LOCK = RLock()
MONEY = Decimal("0.01")
MAX_ACCOUNTS = 20
MAX_TRANSACTIONS = 2000
CONSENT_SCOPE = "bank_data_read"
SUPPORTED_SCOPES = frozenset(
    {
        "accounts.basic",
        "accounts.balance",
        "transactions.read",
        "identity.basic",
    }
)
MORTGAGE_WORDS = (
    "mortgage",
    "home loan",
    "loan payment",
    "mtg",
    "hypotheque",
    "principal interest",
)
PAYROLL_WORDS = ("payroll", "salary", "direct deposit", "paycheque", "paycheck")
INSURANCE_WORDS = ("insurance", "ins ", "premium")
TAX_WORDS = ("property tax", "tax payment", "municipal")


class BankingError(ValueError):
    """Base class for controlled banking-workflow failures."""


class BankingAccessDenied(BankingError):
    """Workspace credentials or tenant boundaries failed validation."""


class ConsentRequired(BankingError):
    """The homeowner has not granted current consent for the requested action."""


class BankingSessionExpired(BankingError):
    """The authorization session can no longer be exchanged."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise BankingError("Expected an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BankingError("Expected a YYYY-MM-DD transaction date") from exc


def _money(value) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    else:
        try:
            amount = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, AttributeError) as exc:
            raise BankingError("Money amounts must be valid decimal numbers") from exc
    if not amount.is_finite():
        raise BankingError("Money amounts must be finite")
    if abs(amount) > Decimal("100000000"):
        raise BankingError("Money amount exceeds safety limit")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(*parts: str, length: int = 24) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise BankingError("Invalid encoded state") from exc


def _json_for_state(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_state(secret: str, payload: dict) -> str:
    return hmac.new(secret.encode("utf-8"), _json_for_state(payload), hashlib.sha256).hexdigest()


def create_signed_state(secret: str, session_id: str, workspace_id: str,
                        client_id: str, nonce: str) -> str:
    payload = {"sid": session_id, "wid": workspace_id, "cid": client_id, "nonce": nonce}
    payload["sig"] = _sign_state(secret, payload)
    return _b64url(_json_for_state(payload))


def decode_signed_state(secret: str, state: str) -> dict:
    try:
        payload = json.loads(_b64url_decode(state).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BankingError("Authorization state is malformed") from exc
    signature = payload.pop("sig", None)
    if not signature or not hmac.compare_digest(signature, _sign_state(secret, payload)):
        raise BankingError("Authorization state failed integrity validation")
    required = {"sid", "wid", "cid", "nonce"}
    if set(payload) != required:
        raise BankingError("Authorization state has unexpected fields")
    return payload


def canonical_scopes(scopes: list[str] | tuple[str, ...] | set[str]) -> tuple[str, ...]:
    if not scopes:
        raise BankingError("At least one banking scope is required")
    normalized: list[str] = []
    for raw in scopes:
        scope = str(raw).strip().lower()
        if scope not in SUPPORTED_SCOPES:
            raise BankingError(f"Unsupported banking scope: {scope}")
        if scope not in normalized:
            normalized.append(scope)
    return tuple(sorted(normalized))


def validate_redirect_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme not in {"https", "http"}:
        raise BankingError("Redirect URI must use http or https")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise BankingError("Plain http redirect URIs are allowed only for localhost")
    if not parsed.netloc or parsed.username or parsed.password:
        raise BankingError("Redirect URI must include a host and no credentials")
    return uri


def mask_identifier(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 4:
        return "****" + digits[-4:]
    if value:
        return "****" + str(value)[-4:]
    return "****"


def redact_description(text: str) -> str:
    output = str(text or "")[:300]
    output = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", output)
    output = re.sub(r"\b\d{3}[- ]?\d{3}[- ]?\d{3}\b", "[9-digit-id]", output)
    output = re.sub(r"(?i)\b(?:acct|account|loan|mortgage|card)\s*(?:no\.?|number|#)\s*[:#-]?\s*[A-Z0-9-]{5,}\b",
                    "[account-ref]", output)
    output = re.sub(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[phone]", output)
    return re.sub(r"\s+", " ", output).strip()


def normalized_payee(text: str) -> str:
    cleaned = redact_description(text).lower()
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    cleaned = re.sub(r"\b(?:preauth|pymt|payment|withdrawal|debit|credit|online|transfer)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80] or "unknown"


def classify_transaction(description: str, amount: Decimal) -> str:
    lower = f" {description.lower()} "
    if any(word in lower for word in MORTGAGE_WORDS) and amount < 0:
        return "mortgage_payment"
    if any(word in lower for word in PAYROLL_WORDS) and amount > 0:
        return "income"
    if any(word in lower for word in TAX_WORDS) and amount < 0:
        return "property_tax"
    if any(word in lower for word in INSURANCE_WORDS) and amount < 0:
        return "insurance"
    if amount < 0:
        return "expense"
    return "deposit"


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    country: str
    sandbox: bool
    supported_scopes: tuple[str, ...]
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str

    def public(self) -> dict:
        data = asdict(self)
        data["supported_scopes"] = list(self.supported_scopes)
        return data


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    provider_account_id_hash: str
    institution_id: str
    display_name: str
    account_type: str
    currency: str
    balance: Decimal
    mask: str
    refreshed_at: str

    def public(self) -> dict:
        data = asdict(self)
        data["balance"] = str(self.balance)
        return data


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    account_id: str
    posted_date: str
    amount: Decimal
    description: str
    payee: str
    category: str
    currency: str
    reference_hash: str

    def public(self) -> dict:
        data = asdict(self)
        data["amount"] = str(self.amount)
        return data


@dataclass(frozen=True)
class PaymentEvidence:
    payee: str
    transaction_count: int
    first_payment_date: str
    last_payment_date: str
    median_amount: Decimal
    cadence_days: int | None
    confidence: str
    sample_descriptions: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["median_amount"] = str(self.median_amount)
        data["sample_descriptions"] = list(self.sample_descriptions)
        return data


def normalize_account(raw: dict, institution_id: str, refreshed_at: str) -> AccountSnapshot:
    provider_id = str(raw.get("provider_account_id") or raw.get("id") or "").strip()
    if not provider_id:
        raise BankingError("Account provider id is required")
    display = str(raw.get("display_name") or raw.get("name") or "Bank account").strip()[:80]
    account_type = str(raw.get("type") or "unknown").strip().lower()[:40]
    currency = str(raw.get("currency") or "CAD").strip().upper()
    if currency != "CAD":
        raise BankingError("Only CAD account snapshots are supported in this release")
    balance = _money(raw.get("balance", "0"))
    account_id = _stable_id(institution_id, provider_id, length=20)
    return AccountSnapshot(
        account_id=account_id,
        provider_account_id_hash=_hash_secret(provider_id),
        institution_id=institution_id,
        display_name=display,
        account_type=account_type,
        currency=currency,
        balance=balance,
        mask=mask_identifier(str(raw.get("mask") or provider_id)),
        refreshed_at=refreshed_at,
    )


def normalize_transaction(raw: dict, account_lookup: dict[str, AccountSnapshot]) -> TransactionRecord:
    provider_account = str(raw.get("provider_account_id") or raw.get("account_id") or "").strip()
    account = account_lookup.get(provider_account)
    if not account:
        raise BankingError("Transaction references an unknown account")
    posted = _parse_iso_date(str(raw.get("posted_date") or raw.get("date") or "")).isoformat()
    amount = _money(raw.get("amount"))
    raw_description = str(raw.get("description") or raw.get("name") or "")
    description = redact_description(raw_description)
    if not description:
        raise BankingError("Transaction description is required")
    currency = str(raw.get("currency") or "CAD").strip().upper()
    if currency != "CAD":
        raise BankingError("Only CAD transaction snapshots are supported")
    reference = str(raw.get("reference") or raw.get("transaction_id") or "")
    reference_hash = _hash_secret(reference) if reference else _stable_id(
        account.account_id, posted, str(amount), description, length=64
    )
    transaction_id = _stable_id(account.account_id, posted, str(amount), description, reference_hash)
    return TransactionRecord(
        transaction_id=transaction_id,
        account_id=account.account_id,
        posted_date=posted,
        amount=amount,
        description=description,
        payee=normalized_payee(raw_description),
        category=classify_transaction(raw_description, amount),
        currency=currency,
        reference_hash=reference_hash,
    )


class SandboxBankProvider:
    """Deterministic provider adapter for local integration and tests."""

    def __init__(self, institution: Institution):
        self.institution = institution

    def authorization_url(self, *, client_id: str, redirect_uri: str, state: str,
                          code_challenge: str, scopes: tuple[str, ...]) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(scopes),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "audience": self.institution.id,
            }
        )
        return f"{self.institution.authorization_endpoint}?{query}"

    def exchange_code(self, code: str, scopes: tuple[str, ...]) -> dict:
        if not str(code).startswith("sandbox-"):
            raise BankingError("Sandbox authorization codes must start with sandbox-")
        nonce = secrets.token_urlsafe(24)
        refresh = secrets.token_urlsafe(32)
        return {
            "access_token": f"access-{self.institution.id}-{nonce}",
            "refresh_token": f"refresh-{self.institution.id}-{refresh}",
            "expires_at": _iso(_now() + timedelta(hours=1)),
            "scopes": list(scopes),
            "token_type": "Bearer",
        }

    def revoke(self, token_digest: str) -> dict:
        return {"revoked": True, "token_digest": token_digest[:12], "provider": self.institution.id}


def default_institutions() -> dict[str, Institution]:
    institutions = [
        Institution(
            id="sandbox-maple-bank",
            name="Maple Bank Sandbox",
            country="CA",
            sandbox=True,
            supported_scopes=tuple(sorted(SUPPORTED_SCOPES)),
            authorization_endpoint="https://sandbox.openbanking.renewal-radar.local/oauth/authorize",
            token_endpoint="https://sandbox.openbanking.renewal-radar.local/oauth/token",
            revocation_endpoint="https://sandbox.openbanking.renewal-radar.local/oauth/revoke",
        ),
        Institution(
            id="sandbox-credit-union",
            name="Community Credit Union Sandbox",
            country="CA",
            sandbox=True,
            supported_scopes=("accounts.basic", "accounts.balance", "transactions.read"),
            authorization_endpoint="https://credit-union.openbanking.renewal-radar.local/oauth/authorize",
            token_endpoint="https://credit-union.openbanking.renewal-radar.local/oauth/token",
            revocation_endpoint="https://credit-union.openbanking.renewal-radar.local/oauth/revoke",
        ),
    ]
    return {item.id: item for item in institutions}


class OpenBankingConnector:
    """Durable consent and snapshot service scoped by broker workspace."""

    def __init__(self, filename: str | Path, state_secret: str | None = None):
        self.filename = str(filename)
        self.state_secret = state_secret or _hash_secret("renewal-radar-local-open-banking-v9")
        self._institutions = default_institutions()
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS banking_sessions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    state_digest TEXT NOT NULL,
                    code_challenge TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    exchanged_at TEXT);
                CREATE INDEX IF NOT EXISTS banking_session_scope
                    ON banking_sessions(workspace_id,client_id,status,created_at);
                CREATE TABLE IF NOT EXISTS banking_connections (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    token_digest TEXT NOT NULL,
                    refresh_digest TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT);
                CREATE INDEX IF NOT EXISTS banking_connection_scope
                    ON banking_connections(workspace_id,client_id,status,created_at);
                CREATE TABLE IF NOT EXISTS banking_accounts (
                    account_id TEXT PRIMARY KEY,
                    connection_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    provider_account_id_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    balance TEXT NOT NULL,
                    mask TEXT NOT NULL,
                    refreshed_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS banking_account_scope
                    ON banking_accounts(workspace_id,client_id,connection_id);
                CREATE TABLE IF NOT EXISTS banking_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    connection_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    posted_date TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payee TEXT NOT NULL,
                    category TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    reference_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS banking_transaction_scope
                    ON banking_transactions(workspace_id,client_id,posted_date,category);
                CREATE TABLE IF NOT EXISTS banking_events (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    client_id TEXT,
                    connection_id TEXT,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    timestamp TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS banking_event_scope
                    ON banking_events(workspace_id,timestamp);
                """
            )

    def _db(self):
        db = sqlite3.connect(self.filename, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def institutions(self) -> list[dict]:
        return [institution.public() for institution in self._institutions.values()]

    def _institution(self, institution_id: str) -> Institution:
        try:
            return self._institutions[institution_id]
        except KeyError as exc:
            raise BankingError("Unknown banking institution") from exc

    def _provider(self, institution_id: str) -> SandboxBankProvider:
        return SandboxBankProvider(self._institution(institution_id))

    def _event(self, db, workspace_id: str, client_id: str | None,
               connection_id: str | None, action: str, detail: dict):
        safe_detail = json.dumps(detail, sort_keys=True, ensure_ascii=True)
        db.execute(
            "INSERT INTO banking_events VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), workspace_id, client_id, connection_id, action, safe_detail, _iso()),
        )

    def _assert_workspace_client(self, broker_workspace, workspace_id: str,
                                 token: str, client_id: str) -> None:
        try:
            clients = broker_workspace.clients(workspace_id, token)
        except Exception as exc:
            raise BankingAccessDenied("Workspace not found") from exc
        if client_id not in {client["id"] for client in clients}:
            raise BankingAccessDenied("Client not found in this workspace")

    def _assert_bank_consent(self, broker_workspace, workspace_id: str,
                             token: str, client_id: str) -> None:
        self._assert_workspace_client(broker_workspace, workspace_id, token, client_id)
        try:
            allowed = broker_workspace.has_consent(workspace_id, token, client_id, CONSENT_SCOPE)
        except Exception as exc:
            raise BankingAccessDenied("Workspace not found") from exc
        if not allowed:
            raise ConsentRequired("Current bank-data consent is required")

    def create_session(self, *, workspace_id: str, broker_token: str, client_id: str,
                       institution_id: str, redirect_uri: str, scopes: list[str],
                       broker_workspace, expires_minutes: int = 15) -> dict:
        self._assert_bank_consent(broker_workspace, workspace_id, broker_token, client_id)
        institution = self._institution(institution_id)
        scope_tuple = canonical_scopes(scopes)
        unsupported = sorted(set(scope_tuple) - set(institution.supported_scopes))
        if unsupported:
            raise BankingError("Institution does not support requested scopes: " + ", ".join(unsupported))
        redirect_uri = validate_redirect_uri(redirect_uri)
        if not 1 <= expires_minutes <= 60:
            raise BankingError("Session expiry must be from 1 through 60 minutes")
        session_id = str(uuid.uuid4())
        nonce = secrets.token_urlsafe(16)
        state = create_signed_state(self.state_secret, session_id, workspace_id, client_id, nonce)
        verifier = secrets.token_urlsafe(48)
        code_challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
        created = _now()
        expires = created + timedelta(minutes=expires_minutes)
        provider = self._provider(institution_id)
        authorization_url = provider.authorization_url(
            client_id="renewal-radar-local",
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            scopes=scope_tuple,
        )
        with _LOCK, self._db() as db:
            db.execute(
                "INSERT INTO banking_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    session_id,
                    workspace_id,
                    client_id,
                    institution_id,
                    json.dumps(list(scope_tuple)),
                    redirect_uri,
                    _hash_secret(state),
                    code_challenge,
                    "created",
                    _iso(created),
                    _iso(expires),
                ),
            )
            self._event(
                db,
                workspace_id,
                client_id,
                None,
                "banking_session_created",
                {"institution_id": institution_id, "scopes": list(scope_tuple), "expires_at": _iso(expires)},
            )
        return {
            "session_id": session_id,
            "institution": institution.public(),
            "authorization_url": authorization_url,
            "state": state,
            "code_challenge": code_challenge,
            "expires_at": _iso(expires),
            "sandbox_code_prefix": "sandbox-",
            "notice": "Sandbox session only; no bank has been contacted.",
        }

    def exchange_session(self, *, workspace_id: str, broker_token: str, session_id: str,
                         authorization_code: str, state: str, broker_workspace) -> dict:
        try:
            broker_workspace._assert_access(workspace_id, broker_token)
        except Exception as exc:
            raise BankingAccessDenied("Workspace not found") from exc
        payload = decode_signed_state(self.state_secret, state)
        if payload["sid"] != session_id or payload["wid"] != workspace_id:
            raise BankingError("Authorization state does not match this session")
        with _LOCK, self._db() as db:
            row = db.execute(
                "SELECT * FROM banking_sessions WHERE id=? AND workspace_id=?",
                (session_id, workspace_id),
            ).fetchone()
            if row is None:
                raise BankingError("Banking session not found")
            if row["status"] != "created":
                raise BankingError("Banking session has already been used")
            if row["state_digest"] != _hash_secret(state):
                raise BankingError("Authorization state does not match the original session")
            if _parse_iso_datetime(row["expires_at"]) < _now():
                db.execute("UPDATE banking_sessions SET status=? WHERE id=?", ("expired", session_id))
                self._event(db, workspace_id, row["client_id"], None, "banking_session_expired", {})
                raise BankingSessionExpired("Banking session expired")
            self._assert_bank_consent(broker_workspace, workspace_id, broker_token, row["client_id"])
            scopes = tuple(json.loads(row["scopes_json"]))
            token = self._provider(row["institution_id"]).exchange_code(authorization_code, scopes)
            connection_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO banking_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    connection_id,
                    session_id,
                    workspace_id,
                    row["client_id"],
                    row["institution_id"],
                    _hash_secret(token["access_token"]),
                    _hash_secret(token["refresh_token"]),
                    json.dumps(token["scopes"]),
                    "active",
                    _iso(),
                    token["expires_at"],
                ),
            )
            db.execute(
                "UPDATE banking_sessions SET status=?, exchanged_at=? WHERE id=?",
                ("exchanged", _iso(), session_id),
            )
            self._event(
                db,
                workspace_id,
                row["client_id"],
                connection_id,
                "banking_connection_active",
                {"institution_id": row["institution_id"], "scopes": token["scopes"]},
            )
            return self._connection_public(db, workspace_id, row["client_id"], connection_id)

    def _connection_public(self, db, workspace_id: str, client_id: str, connection_id: str) -> dict:
        row = db.execute(
            "SELECT * FROM banking_connections WHERE id=? AND workspace_id=? AND client_id=?",
            (connection_id, workspace_id, client_id),
        ).fetchone()
        if not row:
            raise BankingError("Connection not found")
        return {
            "connection_id": row["id"],
            "session_id": row["session_id"],
            "institution_id": row["institution_id"],
            "scopes": json.loads(row["scopes_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "raw_tokens_returned": False,
        }

    def list_connections(self, *, workspace_id: str, broker_token: str, client_id: str,
                         broker_workspace) -> list[dict]:
        self._assert_workspace_client(broker_workspace, workspace_id, broker_token, client_id)
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM banking_connections WHERE workspace_id=? AND client_id=? "
                "ORDER BY created_at DESC,rowid DESC",
                (workspace_id, client_id),
            ).fetchall()
        return [
            {
                "connection_id": row["id"],
                "session_id": row["session_id"],
                "institution_id": row["institution_id"],
                "scopes": json.loads(row["scopes_json"]),
                "status": row["status"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "revoked_at": row["revoked_at"],
                "raw_tokens_returned": False,
            }
            for row in rows
        ]

    def revoke_connection(self, *, workspace_id: str, broker_token: str, client_id: str,
                          connection_id: str, broker_workspace) -> dict:
        self._assert_workspace_client(broker_workspace, workspace_id, broker_token, client_id)
        with _LOCK, self._db() as db:
            row = db.execute(
                "SELECT * FROM banking_connections WHERE id=? AND workspace_id=? AND client_id=?",
                (connection_id, workspace_id, client_id),
            ).fetchone()
            if row is None:
                raise BankingError("Connection not found")
            if row["status"] == "revoked":
                return self._connection_public(db, workspace_id, client_id, connection_id)
            provider_result = self._provider(row["institution_id"]).revoke(row["token_digest"])
            db.execute(
                "UPDATE banking_connections SET status=?, revoked_at=? WHERE id=?",
                ("revoked", _iso(), connection_id),
            )
            self._event(db, workspace_id, client_id, connection_id, "banking_connection_revoked", provider_result)
            return self._connection_public(db, workspace_id, client_id, connection_id)

    def _active_connection(self, db, workspace_id: str, client_id: str, connection_id: str):
        row = db.execute(
            "SELECT * FROM banking_connections WHERE id=? AND workspace_id=? AND client_id=?",
            (connection_id, workspace_id, client_id),
        ).fetchone()
        if row is None:
            raise BankingError("Connection not found")
        if row["status"] != "active":
            raise BankingError("Connection is not active")
        return row

    def import_snapshot(self, *, workspace_id: str, broker_token: str, client_id: str,
                        connection_id: str, accounts: list[dict], transactions: list[dict],
                        broker_workspace, refreshed_at: str | None = None) -> dict:
        self._assert_bank_consent(broker_workspace, workspace_id, broker_token, client_id)
        if not 1 <= len(accounts) <= MAX_ACCOUNTS:
            raise BankingError(f"Supply between 1 and {MAX_ACCOUNTS} accounts")
        if len(transactions) > MAX_TRANSACTIONS:
            raise BankingError(f"Supply at most {MAX_TRANSACTIONS} transactions")
        refreshed_at = refreshed_at or _iso()
        _parse_iso_datetime(refreshed_at)
        with _LOCK, self._db() as db:
            connection = self._active_connection(db, workspace_id, client_id, connection_id)
            account_by_provider: dict[str, AccountSnapshot] = {}
            normalized_accounts: list[AccountSnapshot] = []
            for raw in accounts:
                provider_id = str(raw.get("provider_account_id") or raw.get("id") or "").strip()
                account = normalize_account(raw, connection["institution_id"], refreshed_at)
                account_by_provider[provider_id] = account
                normalized_accounts.append(account)
            normalized_transactions = [
                normalize_transaction(raw, account_by_provider)
                for raw in transactions
            ]
            for account in normalized_accounts:
                db.execute(
                    """INSERT OR REPLACE INTO banking_accounts VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account.account_id,
                        connection_id,
                        workspace_id,
                        client_id,
                        account.institution_id,
                        account.provider_account_id_hash,
                        account.display_name,
                        account.account_type,
                        account.currency,
                        str(account.balance),
                        account.mask,
                        account.refreshed_at,
                    ),
                )
            inserted_transactions = 0
            for tx in normalized_transactions:
                cursor = db.execute(
                    """INSERT OR IGNORE INTO banking_transactions VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        tx.transaction_id,
                        connection_id,
                        workspace_id,
                        client_id,
                        tx.account_id,
                        tx.posted_date,
                        str(tx.amount),
                        tx.description,
                        tx.payee,
                        tx.category,
                        tx.currency,
                        tx.reference_hash,
                    ),
                )
                inserted_transactions += cursor.rowcount
            self._event(
                db,
                workspace_id,
                client_id,
                connection_id,
                "banking_snapshot_imported",
                {"accounts": len(normalized_accounts), "transactions": inserted_transactions},
            )
            return {
                "accounts_imported": len(normalized_accounts),
                "transactions_imported": inserted_transactions,
                "transactions_seen": len(normalized_transactions),
                "stored_raw_tokens": False,
                "stored_full_account_numbers": False,
            }

    def accounts(self, *, workspace_id: str, broker_token: str, client_id: str,
                 broker_workspace) -> list[dict]:
        self._assert_workspace_client(broker_workspace, workspace_id, broker_token, client_id)
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM banking_accounts WHERE workspace_id=? AND client_id=? "
                "ORDER BY display_name,account_id",
                (workspace_id, client_id),
            ).fetchall()
        return [
            AccountSnapshot(
                account_id=row["account_id"],
                provider_account_id_hash=row["provider_account_id_hash"],
                institution_id=row["institution_id"],
                display_name=row["display_name"],
                account_type=row["account_type"],
                currency=row["currency"],
                balance=Decimal(row["balance"]),
                mask=row["mask"],
                refreshed_at=row["refreshed_at"],
            ).public()
            for row in rows
        ]

    def _transactions(self, db, workspace_id: str, client_id: str,
                      months: int = 18) -> list[TransactionRecord]:
        if not 1 <= months <= 36:
            raise BankingError("Months must be from 1 through 36")
        cutoff = (_now().date() - timedelta(days=months * 31)).isoformat()
        rows = db.execute(
            """SELECT * FROM banking_transactions
               WHERE workspace_id=? AND client_id=? AND posted_date>=?
               ORDER BY posted_date,transaction_id""",
            (workspace_id, client_id, cutoff),
        ).fetchall()
        return [
            TransactionRecord(
                transaction_id=row["transaction_id"],
                account_id=row["account_id"],
                posted_date=row["posted_date"],
                amount=Decimal(row["amount"]),
                description=row["description"],
                payee=row["payee"],
                category=row["category"],
                currency=row["currency"],
                reference_hash=row["reference_hash"],
            )
            for row in rows
        ]

    def payment_evidence(self, *, workspace_id: str, broker_token: str, client_id: str,
                         broker_workspace, months: int = 18,
                         lender_hint: str | None = None) -> dict:
        self._assert_bank_consent(broker_workspace, workspace_id, broker_token, client_id)
        with self._db() as db:
            transactions = self._transactions(db, workspace_id, client_id, months)
        hint = normalized_payee(lender_hint or "") if lender_hint else None
        mortgage_candidates = []
        for tx in transactions:
            hint_match = hint and hint in tx.payee
            if tx.category == "mortgage_payment" or hint_match:
                if tx.amount < 0:
                    mortgage_candidates.append(tx)
        grouped: dict[str, list[TransactionRecord]] = {}
        for tx in mortgage_candidates:
            grouped.setdefault(tx.payee, []).append(tx)
        evidence: list[PaymentEvidence] = []
        for payee, items in grouped.items():
            items = sorted(items, key=lambda item: item.posted_date)
            if len(items) < 2:
                cadence = None
                confidence = "low"
            else:
                dates = [_parse_iso_date(item.posted_date) for item in items]
                gaps = [(right - left).days for left, right in zip(dates, dates[1:]) if right >= left]
                cadence = round(median(gaps)) if gaps else None
                confidence = "high" if len(items) >= 3 and cadence and 20 <= cadence <= 40 else "medium"
            amounts = [abs(item.amount) for item in items]
            samples = tuple(dict.fromkeys(item.description for item in items[:3]))
            evidence.append(
                PaymentEvidence(
                    payee=payee,
                    transaction_count=len(items),
                    first_payment_date=items[0].posted_date,
                    last_payment_date=items[-1].posted_date,
                    median_amount=median(amounts).quantize(MONEY),
                    cadence_days=cadence,
                    confidence=confidence,
                    sample_descriptions=samples,
                )
            )
        evidence.sort(key=lambda item: (-item.transaction_count, item.payee))
        return {
            "evidence": [item.public() for item in evidence],
            "transaction_window_months": months,
            "transactions_considered": len(transactions),
            "notice": "Banking evidence can corroborate payment cadence only; it is not a lender payout statement.",
        }

    def cashflow_summary(self, *, workspace_id: str, broker_token: str, client_id: str,
                         broker_workspace, months: int = 6) -> dict:
        self._assert_bank_consent(broker_workspace, workspace_id, broker_token, client_id)
        with self._db() as db:
            transactions = self._transactions(db, workspace_id, client_id, months)
        income = sum((tx.amount for tx in transactions if tx.amount > 0), Decimal("0.00"))
        expenses = sum((-tx.amount for tx in transactions if tx.amount < 0), Decimal("0.00"))
        by_category: dict[str, Decimal] = {}
        for tx in transactions:
            by_category[tx.category] = by_category.get(tx.category, Decimal("0.00")) + tx.amount
        return {
            "months": months,
            "income": str(income.quantize(MONEY)),
            "expenses": str(expenses.quantize(MONEY)),
            "net": str((income - expenses).quantize(MONEY)),
            "categories": {key: str(value.quantize(MONEY)) for key, value in sorted(by_category.items())},
            "notice": "Cashflow summary is derived from imported snapshots, not a live bank feed.",
        }

    def events(self, *, workspace_id: str, broker_token: str, broker_workspace,
               client_id: str | None = None, limit: int = 100) -> list[dict]:
        try:
            broker_workspace._assert_access(workspace_id, broker_token)
        except Exception as exc:
            raise BankingAccessDenied("Workspace not found") from exc
        if not 1 <= limit <= 500:
            raise BankingError("Invalid event limit")
        params: list = [workspace_id]
        sql = "SELECT * FROM banking_events WHERE workspace_id=?"
        if client_id:
            sql += " AND client_id=?"
            params.append(client_id)
        sql += " ORDER BY timestamp DESC,rowid DESC LIMIT ?"
        params.append(limit)
        with self._db() as db:
            return [dict(row) for row in db.execute(sql, params)]
