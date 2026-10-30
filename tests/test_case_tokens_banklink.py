"""Broker-first case tokens and banklink PKCE binding."""
from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


@pytest.fixture
def demo_ws(monkeypatch):
    monkeypatch.setenv("RR_ENABLE_DEMO_WORKSPACES", "1")
    monkeypatch.setenv("RR_ENABLE_BANKLINK_SANDBOX", "1")
    from renewal import main

    with TestClient(main.app) as c:
        ws = c.post("/api/v4/broker/workspaces", json={"name": "Case Token WS"}).json()
        yield c, ws


def _create_case(c, ws, scopes=None):
    d = c.get("/api/demo").json()
    case = c.post(
        "/api/cases",
        json={
            "title": "Bound case",
            "workspace_id": ws["workspace_id"],
            "mortgage": d["mortgage"],
            "offers": d["offers"],
        },
        headers={"X-Broker-Token": ws["access_token"]},
    )
    assert case.status_code == 201, case.text
    body = case.json()
    assert "access_token" not in body
    assert body["workspace_id"] == ws["workspace_id"]
    token = None
    if scopes:
        minted = c.post(
            f"/api/cases/{body['id']}/tokens",
            json={"scopes": scopes, "ttl_seconds": 3600},
            headers={"X-Broker-Token": ws["access_token"]},
        )
        assert minted.status_code == 201, minted.text
        token = minted.json()["token"]
    return body, token


def test_create_case_requires_broker(demo_ws):
    c, ws = demo_ws
    d = c.get("/api/demo").json()
    # missing broker token
    r = c.post(
        "/api/cases",
        json={"title": "x", "workspace_id": ws["workspace_id"], "mortgage": d["mortgage"], "offers": []},
    )
    assert r.status_code == 404
    # api key alone still no broker — wrong token
    r = c.post(
        "/api/cases",
        json={"title": "x", "workspace_id": ws["workspace_id"], "mortgage": d["mortgage"], "offers": []},
        headers={"X-Broker-Token": "not-a-real-token", "X-Api-Key": "k" * 32},
    )
    assert r.status_code == 404


def test_api_key_alone_cannot_mint_case_token(demo_ws, monkeypatch):
    c, ws = demo_ws
    case, _ = _create_case(c, ws)
    # No broker token
    r = c.post(
        f"/api/cases/{case['id']}/tokens",
        json={"scopes": ["case:read"], "ttl_seconds": 600},
    )
    assert r.status_code == 404
    # Explicit api key without broker still fails
    monkeypatch.setenv("RR_API_ACCESS_KEY", "k" * 32)
    r = c.post(
        f"/api/cases/{case['id']}/tokens",
        json={"scopes": ["case:read"], "ttl_seconds": 600},
        headers={"X-Api-Key": "k" * 32},
    )
    assert r.status_code == 404


def test_case_auth_and_expiring_links_broker_first(demo_ws):
    c, ws = demo_ws
    case, token = _create_case(c, ws, scopes=["case:read", "case:write", "case:share"])
    cid = case["id"]
    assert c.get("/api/cases/" + cid).status_code == 404
    assert c.get("/api/cases/" + cid, headers={"X-Case-Token": "bad"}).status_code == 404
    assert c.get("/api/cases/" + cid, headers={"X-Case-Token": token}).status_code == 200
    share = c.post(
        "/api/cases/" + cid + "/share",
        json={"expires_hours": 1},
        headers={"X-Case-Token": token},
    ).json()
    assert share["url_path"].startswith("/shared/")
    assert c.get("/api/shares/" + share["token"]).status_code == 200
    assert c.delete(
        "/api/cases/" + cid + "/shares/" + share["token"], headers={"X-Case-Token": token}
    ).json()["revoked"]
    assert c.get("/api/shares/" + share["token"]).status_code == 404


def test_banklink_pkce_complete_and_revoke(demo_ws):
    c, ws = demo_ws
    case, token = _create_case(c, ws, scopes=["banklink:connect", "banklink:read", "case:read"])
    verifier, challenge = _pkce_pair()
    consent = c.post(
        "/api/v5/banklink/consents",
        json={
            "case_id": case["id"],
            "workspace_id": ws["workspace_id"],
            "provider": "plaid",
            "purpose": "renewal_analysis",
        },
        headers={"X-Broker-Token": ws["access_token"]},
    )
    assert consent.status_code == 201, consent.text
    cid = consent.json()["consent_id"]

    # Session requires case token + challenge
    assert c.post(f"/api/v5/banklink/consents/{cid}/session", json={}).status_code == 403
    sess = c.post(
        f"/api/v5/banklink/consents/{cid}/session",
        json={"code_challenge": challenge, "bind_cookie": True},
        headers={"X-Case-Token": token},
    )
    assert sess.status_code == 200, sess.text
    state = sess.json()["state"]
    cookie = sess.cookies.get("rr_banklink_nonce")
    assert cookie

    # Wrong browser cookie
    bad = c.post(
        "/api/v5/banklink/complete",
        json={
            "state": state,
            "code_verifier": verifier,
            "public_token": "t",
            "cookie_nonce": "wrong-browser",
        },
    )
    assert bad.status_code == 403
    assert "browser" in bad.json()["detail"].lower() or "binding" in bad.json()["detail"].lower()

    # Success with correct cookie
    ok = c.post(
        "/api/v5/banklink/complete",
        json={
            "state": state,
            "code_verifier": verifier,
            "public_token": "t",
            "cookie_nonce": cookie,
        },
    )
    assert ok.status_code == 200, ok.text
    link = ok.json()["link_id"]

    # Replay state
    replay = c.post(
        "/api/v5/banklink/complete",
        json={
            "state": state,
            "code_verifier": verifier,
            "public_token": "t",
            "cookie_nonce": cookie,
        },
    )
    assert replay.status_code == 403

    # Mortgages via broker
    m = c.get(
        f"/api/v5/banklink/links/{link}/mortgages",
        headers={"X-Broker-Token": ws["access_token"]},
    )
    assert m.status_code == 200
    assert m.json()["mortgages"][0]["balance"] == "412345.67"

    # Mortgages via case token
    m2 = c.get(
        f"/api/v5/banklink/links/{link}/mortgages",
        headers={"X-Case-Token": token},
    )
    assert m2.status_code == 200

    # Revoke idempotent
    assert (
        c.delete(
            f"/api/v5/banklink/consents/{cid}",
            headers={"X-Broker-Token": ws["access_token"]},
        ).status_code
        == 204
    )
    assert (
        c.delete(
            f"/api/v5/banklink/consents/{cid}",
            headers={"X-Broker-Token": ws["access_token"]},
        ).status_code
        == 204
    )
    assert (
        c.get(
            f"/api/v5/banklink/links/{link}/mortgages",
            headers={"X-Broker-Token": ws["access_token"]},
        ).status_code
        == 403
    )


def test_banklink_expired_state(demo_ws):
    c, ws = demo_ws
    case, token = _create_case(c, ws, scopes=["banklink:connect"])
    verifier, challenge = _pkce_pair()
    consent = c.post(
        "/api/v5/banklink/consents",
        json={
            "case_id": case["id"],
            "workspace_id": ws["workspace_id"],
            "provider": "plaid",
            "purpose": "renewal_analysis",
        },
        headers={"X-Broker-Token": ws["access_token"]},
    ).json()
    cid = consent["consent_id"]
    sess = c.post(
        f"/api/v5/banklink/consents/{cid}/session",
        json={"code_challenge": challenge, "bind_cookie": False},
        headers={"X-Case-Token": token},
    )
    state = sess.json()["state"]
    from renewal import main

    # Expire pending state via gateway clock/mutate
    pending = main.banklink_gateway._states[state]
    main.banklink_gateway._states[state] = type(pending)(
        state=pending.state,
        consent_id=pending.consent_id,
        code_challenge=pending.code_challenge,
        cookie_nonce=pending.cookie_nonce,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        claimed=pending.claimed,
    )
    expired = c.post(
        "/api/v5/banklink/complete",
        json={"state": state, "code_verifier": verifier, "public_token": "t"},
    )
    assert expired.status_code == 403
    assert "expir" in expired.json()["detail"].lower()


def test_complete_is_public_path():
    from renewal.security import access

    assert access.path_allows_anonymous("/api/v5/banklink/complete")
    assert not access.path_allows_anonymous("/api/v5/banklink/consents")
