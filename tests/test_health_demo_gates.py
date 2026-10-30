"""Public health strip + production demo rejection."""
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.security import access


def test_legacy_health_is_public_and_minimal():
    with TestClient(app) as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_ready_still_has_details():
    with TestClient(app) as c:
        r = c.get("/api/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert "checks" in body and "connectors" in body


def test_demo_rejected_in_production(monkeypatch):
    monkeypatch.setattr(access, "_env_name", lambda: "production")
    monkeypatch.setenv("RR_ENABLE_DEMO_WORKSPACES", "1")  # even if set, prod blocks
    monkeypatch.setenv("RR_API_ACCESS_KEY", "k" * 32)
    with TestClient(app) as c:
        headers = {"X-Api-Key": "k" * 32}
        assert c.get("/api/demo", headers=headers).status_code == 404
        assert c.post("/api/v4/broker/workspaces", headers=headers, json={"name": "X"}).status_code == 403
