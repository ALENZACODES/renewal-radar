"""SQLite demo case store: workspace-owned cases and hashed credentials.

IMPORTANT: no mortgage PDF binary, bank account identifiers or name is persisted.
The store is demo/workspace functionality; production deployments must add an
identity provider, tenant policy and encryption-at-rest infrastructure.

Case create no longer returns a long-lived access token. Mint scoped tokens via
``renewal.cases.tokens`` (HMAC/SHA-256 hash at rest, TTL, allowlisted scopes).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..config import settings


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = 'cases'
    id = Column(String(64), primary_key=True)
    # Legacy single-secret hash (optional; new cases leave empty and use CaseTokenStore).
    secret_hash = Column(String(64), nullable=False, default='')
    workspace_id = Column(String(64), nullable=True)
    title = Column(String(120), nullable=False)
    payload = Column(Text, nullable=False)
    created = Column(DateTime(timezone=True), nullable=False)
    updated = Column(DateTime(timezone=True), nullable=False)


class Share(Base):
    __tablename__ = 'shares'
    token_hash = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False)
    expires = Column(DateTime(timezone=True), nullable=False)


ROOT = Path(__file__).resolve().parents[3]


def database_url() -> str:
    url = settings.database_url
    if not url.startswith('sqlite:///') or url == 'sqlite:///:memory:':
        return url
    raw = url.removeprefix('sqlite:///')
    if raw.startswith('/'):
        target = Path(raw)
    else:
        target = (ROOT / raw).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return 'sqlite:///' + target.as_posix()


engine = create_engine(
    database_url(),
    connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite:') else {},
    pool_pre_ping=True,
)
Session = sessionmaker(engine, expire_on_commit=False)


def initialize():
    Base.metadata.create_all(engine)
    # Lightweight migration for existing SQLite demo DBs.
    if settings.database_url.startswith('sqlite:'):
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info(cases)').fetchall()}
            if 'workspace_id' not in cols:
                conn.exec_driver_sql('ALTER TABLE cases ADD COLUMN workspace_id VARCHAR(64)')


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def create_case(title, payload, workspace_id: str | None = None, *, mint_legacy_token: bool = False):
    """Create a case owned by ``workspace_id``. Does not mint an access token by default."""
    now = utcnow()
    uid = str(uuid.uuid4())
    legacy = ''
    plaintext = None
    if mint_legacy_token:
        plaintext = secrets.token_urlsafe(32)
        legacy = sha(plaintext)
    with Session() as session:
        session.add(
            Case(
                id=uid,
                secret_hash=legacy,
                workspace_id=workspace_id,
                title=title,
                payload=json.dumps(payload),
                created=now,
                updated=now,
            )
        )
        session.commit()
    out = {'id': uid, 'title': title, 'created_at': now.isoformat(), 'workspace_id': workspace_id}
    if plaintext is not None:
        out['access_token'] = plaintext  # legacy path only
    return out


def get_case_meta(uid: str) -> dict | None:
    with Session() as s:
        obj = s.get(Case, uid)
        if not obj:
            return None
        return {
            'id': obj.id,
            'title': obj.title,
            'workspace_id': obj.workspace_id,
            'created_at': obj.created.isoformat(),
        }


def read_case(uid, token):
    """Authorize via scoped case token (case:read|case:write) OR legacy secret_hash."""
    from ..cases.tokens import case_tokens

    with Session() as s:
        obj = s.get(Case, uid)
        if not obj:
            return None
        ok = False
        if obj.secret_hash and secrets.compare_digest(obj.secret_hash, sha(token or '')):
            ok = True
        elif case_tokens.verify(uid, token, required='case:read') is not None:
            ok = True
        elif case_tokens.verify(uid, token, required='case:write') is not None:
            ok = True
        if not ok:
            return None
        return {
            'id': obj.id,
            'title': obj.title,
            'data': json.loads(obj.payload),
            'created_at': obj.created.isoformat(),
            'workspace_id': obj.workspace_id,
        }


def case_belongs_to_workspace(uid: str, workspace_id: str) -> bool:
    meta = get_case_meta(uid)
    return bool(meta and meta.get('workspace_id') == workspace_id)


def update_case(uid, token, payload):
    from ..cases.tokens import case_tokens

    with Session() as s:
        obj = s.get(Case, uid)
        if not obj:
            return False
        ok = False
        if obj.secret_hash and secrets.compare_digest(obj.secret_hash, sha(token or '')):
            ok = True
        elif case_tokens.verify(uid, token, required='case:write') is not None:
            ok = True
        if not ok:
            return False
        obj.payload = json.dumps(payload)
        obj.updated = utcnow()
        s.commit()
        return True


def create_share(uid, access_token, hours=24):
    from ..cases.tokens import case_tokens

    with Session() as s:
        obj = s.get(Case, uid)
        if not obj:
            return None
        ok = False
        if obj.secret_hash and secrets.compare_digest(obj.secret_hash, sha(access_token or '')):
            ok = True
        elif case_tokens.verify(uid, access_token, required='case:share') is not None:
            ok = True
        if not ok:
            return None
        token = secrets.token_urlsafe(32)
        exp = utcnow() + timedelta(hours=hours)
        s.add(Share(token_hash=sha(token), case_id=uid, expires=exp))
        s.commit()
        return {'token': token, 'expires_at': exp.isoformat()}


def read_share(token):
    with Session() as s:
        share = s.get(Share, sha(token))
        if not share or share.expires.replace(tzinfo=timezone.utc) < utcnow():
            return None
        obj = s.get(Case, share.case_id)
        if not obj:
            return None
        payload = json.loads(obj.payload)
        return {
            'title': obj.title,
            'mortgage': payload.get('mortgage'),
            'offers': payload.get('offers', []),
            'shared_at': utcnow().isoformat(),
            'notice': 'Read-only financial planning data. No approval or lender quote implied.',
        }


def revoke_share(uid, access_token, token):
    from ..cases.tokens import case_tokens

    with Session() as s:
        obj = s.get(Case, uid)
        if not obj:
            return False
        ok = False
        if obj.secret_hash and secrets.compare_digest(obj.secret_hash, sha(access_token or '')):
            ok = True
        elif case_tokens.verify(uid, access_token, required='case:share') is not None:
            ok = True
        if not ok:
            return False
        share = s.get(Share, sha(token))
        if not share or share.case_id != uid:
            return False
        s.delete(share)
        s.commit()
        return True
