"""Regression: non-public HTTP routes must sit behind the API access gate."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.security import access


def test_app_registers_require_api_access_dependency():
    assert access.app_has_access_gate(app), (
        "FastAPI app must declare Depends(require_api_access) so every route "
        "inherits the production fail-closed gate"
    )


def test_non_public_api_routes_are_covered_by_gate_or_resource_auth():
    """Every /api route is either allowlisted, capability-URL, or gated.

    The global Depends(require_api_access) covers routes that have no
    resource token. Routes that already take broker/case/OCR/ingest headers
    still inherit the gate (defense in depth in production).
    """
    assert access.app_has_access_gate(app)
    uncovered = []
    for route in access.iter_api_routes(app):
        methods = sorted(m for m in route.methods if m not in {"HEAD", "OPTIONS"})
        if not methods:
            continue
        path = route.path
        if not path.startswith("/api"):
            continue
        if access.path_allows_anonymous(path):
            continue
        # Inherits app-level gate — required.
        headers = access.route_header_names(route)
        deps = access.route_dependency_names(route)
        has_gate = access.AUTH_DEP_NAME in deps or access.app_has_access_gate(app)
        if not has_gate:
            uncovered.append(f"{','.join(methods)} {path} headers={headers}")
    assert not uncovered, "routes missing auth gate:\n" + "\n".join(uncovered)


def test_production_fails_closed_without_api_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("RR_API_ACCESS_KEY", raising=False)
    # settings.app_env is frozen at import — patch the helper instead
    monkeypatch.setattr(access, "_env_name", lambda: "production")
    with TestClient(app) as client:
        live = client.get("/api/health/live")
        assert live.status_code == 200 and live.json()["status"] == "alive"
        blocked = client.get("/api/policy")
        assert blocked.status_code == 503
        assert "RR_API_ACCESS_KEY" in blocked.json()["detail"]


def test_production_accepts_configured_api_key(monkeypatch):
    key = "k" * 32
    monkeypatch.setattr(access, "_env_name", lambda: "production")
    monkeypatch.setenv("RR_API_ACCESS_KEY", key)
    with TestClient(app) as client:
        denied = client.get("/api/policy")
        assert denied.status_code == 401
        ok = client.get("/api/policy", headers={"X-Api-Key": key})
        assert ok.status_code == 200


def test_public_allowlist_does_not_include_analysis_apis():
    risky = [
        "/api/analyze",
        "/api/documents/extract",
        "/api/v5/banklink/providers",
        "/api/v5/leads",
        "/api/v4/broker/workspaces",
        "/api/agent/run",
        "/api/ratewatch/live",
    ]
    for path in risky:
        assert not access.path_allows_anonymous(path), path
