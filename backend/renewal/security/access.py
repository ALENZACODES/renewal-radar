"""API access gate: public allowlist + production fail-closed API key.

Existing resource tokens (X-Broker-Token, X-Case-Token, X-OCR-Review-Token,
X-Rate-Ingest-Key, share-URL tokens) remain the fine-grained controls. This
module adds a process-wide gate so anonymous callers cannot hit analysis, OCR,
bank-link or broker APIs in production when RR_API_ACCESS_KEY is unset or wrong.

Pattern matches rate ingestion: secrets.compare_digest on a shared secret header.
"""
from __future__ import annotations

import os
import re
import secrets
from typing import Callable, Iterable

from fastapi import Header, HTTPException, Request

from ..config import settings

# Exact paths that need no credential (probes + static shell).
PUBLIC_EXACT: frozenset[str] = frozenset({
    '/api/health',
    '/api/health/live',
    '/api/health/ready',
    '/',
    '/service-worker.js',
    '/robots.txt',
})

# Prefixes for packaged frontend assets.
PUBLIC_PREFIXES: tuple[str, ...] = (
    '/assets/',
    '/js/',
)

# Capability-URL resources: the path token *is* the credential.
CAPABILITY_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'^/api/shares/[^/]+$'),
    re.compile(r'^/shared/[^/]+$'),
)

# OpenAPI UIs — allowed only outside production; production requires the API key.
DOCS_EXACT: frozenset[str] = frozenset({
    '/docs',
    '/docs/oauth2-redirect',
    '/redoc',
    '/openapi.json',
})

# Header names that count as route-level auth for inventory / regression tests.
RESOURCE_AUTH_HEADERS: frozenset[str] = frozenset({
    'x-broker-token',
    'x-case-token',
    'x-ocr-review-token',
    'x-rate-ingest-key',
    'x-api-key',
})

AUTH_DEP_NAME = 'require_api_access'


def _env_name() -> str:
    return (settings.app_env or os.environ.get('APP_ENV') or 'development').strip().lower()


def is_production() -> bool:
    return _env_name() in {'production', 'prod'}


def demo_enabled() -> bool:
    """Demo *data-mutating* features (e.g. mint workspaces). Never in production."""
    if is_production():
        return False
    return os.environ.get('RR_ENABLE_DEMO_WORKSPACES') == '1'


def demo_samples_allowed() -> bool:
    """Read-only demo JSON/fixtures. Available in non-production; blocked in production."""
    return not is_production()


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    if path in DOCS_EXACT and not is_production():
        return True
    return False


def is_capability_url(path: str) -> bool:
    return any(p.match(path) for p in CAPABILITY_URL_PATTERNS)


def path_allows_anonymous(path: str) -> bool:
    """True when the gate should not demand X-Api-Key."""
    return is_public_path(path) or is_capability_url(path)


def configured_api_key() -> str:
    return os.environ.get('RR_API_ACCESS_KEY', '') or ''


async def require_api_access(
    request: Request,
    x_api_key: str | None = Header(default=None, alias='X-Api-Key'),
) -> dict:
    """Fail closed in production; optional enforcement in development when configured."""
    path = request.url.path
    if path_allows_anonymous(path):
        return {'mode': 'public' if is_public_path(path) else 'capability_url'}

    expected = configured_api_key()
    if is_production():
        if len(expected) < 24:
            raise HTTPException(
                status_code=503,
                detail='API access key is not configured (set RR_API_ACCESS_KEY, min 24 chars).',
            )
        if not x_api_key or not secrets.compare_digest(x_api_key, expected):
            raise HTTPException(status_code=401, detail='Unauthorized')
        return {'mode': 'api_key'}

    # Development / test: open unless an access key has been explicitly configured.
    if expected:
        if len(expected) < 24 or not x_api_key or not secrets.compare_digest(x_api_key, expected):
            raise HTTPException(status_code=401, detail='Unauthorized')
        return {'mode': 'api_key'}
    return {'mode': 'dev_open'}


def route_resource_auth_headers(header_names: Iterable[str]) -> list[str]:
    return sorted({h.lower() for h in header_names if h.lower() in RESOURCE_AUTH_HEADERS})


def iter_api_routes(app) -> list:
    """Flatten APIRoute objects, including FastAPI _IncludedRouter wrappers."""
    from fastapi.routing import APIRoute

    out = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            out.append(route)
        elif type(route).__name__ == '_IncludedRouter':
            orig = getattr(route, 'original_router', None)
            if orig is None:
                continue
            for sub in orig.routes:
                if isinstance(sub, APIRoute):
                    out.append(sub)
    return out


def route_header_names(route) -> list[str]:
    names: list[str] = []

    def walk(dep) -> None:
        for p in dep.header_params:
            names.append((p.alias or p.name).lower())
        for child in dep.dependencies:
            walk(child)

    walk(route.dependant)
    return names


def route_dependency_names(route) -> list[str]:
    names: list[str] = []

    def walk(dep) -> None:
        if dep.call is not None:
            names.append(getattr(dep.call, '__name__', str(dep.call)))
        for child in dep.dependencies:
            walk(child)

    walk(route.dependant)
    return names


def app_has_access_gate(app) -> bool:
    for dep in app.router.dependencies:
        call = getattr(dep, 'dependency', None) or getattr(dep, 'call', None)
        # FastAPI stores Depends objects; .dependency is the callable
        fn = getattr(dep, 'dependency', None)
        if fn is require_api_access or getattr(fn, '__name__', '') == AUTH_DEP_NAME:
            return True
    return False
