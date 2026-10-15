"""Cross-tenant negative tests for lead create/delete."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from renewal.leads.consent import CURRENT_VERSION, CONSENT_TEXTS
from renewal.leads.identity import Vault


def _enable_leads(monkeypatch, tmp_path, main):
    monkeypatch.setenv("RR_ENABLE_DEMO_WORKSPACES", "1")
    monkeypatch.setenv("RR_LEAD_KEY", Vault.new_key().decode())
    monkeypatch.setenv("RR_LEAD_DEDUPE_SECRET", "d" * 32)
    monkeypatch.setattr(main, "_lead_engine", None)
    monkeypatch.setattr(main, "LEADS_DB", tmp_path / "xtenant-leads.sqlite3")


def _consent():
    text = CONSENT_TEXTS[CURRENT_VERSION]
    return {
        "version": text.version,
        "text_digest": text.digest,
        "agreed": True,
        "agreed_at": datetime.now(timezone.utc).isoformat(),
        "contact_methods": ["email"],
        "brokerage": "Broker",
    }


def test_cannot_create_lead_in_another_workspace(monkeypatch, tmp_path):
    from renewal import main

    _enable_leads(monkeypatch, tmp_path, main)
    with TestClient(main.app) as c:
        a = c.post("/api/v4/broker/workspaces", json={"name": "A"}).json()
        b = c.post("/api/v4/broker/workspaces", json={"name": "B"}).json()
        body = {
            "name": "Pat Lee",
            "email": "pat@example.ca",
            "province": "ON",
            "renewal_date": "2026-12-15",
            "balance": "350000",
            "current_rate": "5.6",
            "consent": {**_consent(), "brokerage": "A"},
        }
        # Broker A token against Broker B workspace path
        r = c.post(
            f"/api/v5/broker/workspaces/{b['workspace_id']}/leads",
            headers={"X-Broker-Token": a["access_token"]},
            json=body,
        )
        assert r.status_code == 404
        # Legacy path with spoofed workspace_id also 404
        legacy = c.post(
            "/api/v5/leads",
            headers={"X-Broker-Token": a["access_token"]},
            json={**body, "workspace_id": b["workspace_id"]},
        )
        assert legacy.status_code == 404
        # No token at all
        assert (
            c.post(f"/api/v5/broker/workspaces/{a['workspace_id']}/leads", json=body).status_code
            == 404
        )


def test_cannot_delete_other_tenant_lead(monkeypatch, tmp_path):
    from renewal import main

    _enable_leads(monkeypatch, tmp_path, main)
    with TestClient(main.app) as c:
        a = c.post("/api/v4/broker/workspaces", json={"name": "A"}).json()
        b = c.post("/api/v4/broker/workspaces", json={"name": "B"}).json()
        body = {
            "name": "Sam Lee",
            "email": "sam.xt@example.ca",
            "province": "AB",
            "renewal_date": "2026-12-15",
            "balance": "350000",
            "current_rate": "5.6",
            "consent": {**_consent(), "brokerage": "A"},
        }
        created = c.post(
            f"/api/v5/broker/workspaces/{a['workspace_id']}/leads",
            headers={"X-Broker-Token": a["access_token"]},
            json=body,
        ).json()
        # Broker B tries to delete A's lead — must be 404 (no existence leak)
        denied = c.request(
            "DELETE",
            f"/api/v5/leads/{created['id']}",
            headers={"X-Broker-Token": b["access_token"]},
            json={},
        )
        assert denied.status_code == 404
        # Wrong withdraw token — 404
        wrong = c.request(
            "DELETE",
            f"/api/v5/leads/{created['id']}",
            json={"withdraw_token": "not-the-token"},
        )
        assert wrong.status_code == 404
        # Owner withdraw still works
        ok = c.request(
            "DELETE",
            f"/api/v5/leads/{created['id']}",
            json={"withdraw_token": created["withdraw_token"]},
        )
        assert ok.status_code == 204


def test_client_cannot_set_id_status_or_created_by(monkeypatch, tmp_path):
    from renewal import main

    _enable_leads(monkeypatch, tmp_path, main)
    with TestClient(main.app) as c:
        w = c.post("/api/v4/broker/workspaces", json={"name": "A"}).json()
        body = {
            "id": "client-chosen-id",
            "status": "hot",
            "created_by": "attacker",
            "workspace_id": "ignored-spoof",
            "name": "Sam Lee",
            "email": "sam2@example.ca",
            "province": "AB",
            "consent": {**_consent(), "brokerage": "A"},
        }
        r = c.post(
            f"/api/v5/broker/workspaces/{w['workspace_id']}/leads",
            headers={"X-Broker-Token": w["access_token"]},
            json=body,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["id"] != "client-chosen-id"
        assert data["created_by"] == w["workspace_id"]
