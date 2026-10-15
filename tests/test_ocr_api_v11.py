from fastapi.testclient import TestClient

from renewal import main
from renewal.ocr.review_sessions import OCRReviewSessionStore


OCR_TEXT = """
Maple Bank Mortgage Renewal Agreement
Mortgage number: ABCD-1234-5678
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Current interest rate: 4.39%
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Renewal term: 60 months
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Payment amount: $3,285.00
Payment frequency: monthly
Interest rate differential applies if discharged early.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def page_payload(text=OCR_TEXT):
    return {
        "filename": "renewal-ocr.txt",
        "pages": [{"page_number": 1, "text": text, "mean_confidence": 0.93}],
    }


def token_headers(token):
    return {"X-OCR-Review-Token": token}


def test_ocr_understand_endpoint_reads_fine_details():
    with TestClient(main.app) as http:
        response = http.post("/api/v11/ocr/understand", json=page_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["classification"]["type"] == "renewal_offer"
    assert body["extraction"]["fields"]["contract_rate"]["value"] == 4.39
    assert body["extraction"]["fields"]["posted_rate"]["value"] == 5.69
    assert body["extraction"]["fields"]["contract_discount"]["value"] == 1.3
    assert body["extraction"]["fields"]["mortgage_start_date"]["value"] == "2022-03-01"
    assert body["canadian_mortgage_terms"]["calculations"]["contract_discount"]["status"] == "matches"
    assert any(item["clause"] == "interest_rate_differential" for item in body["clauses"])
    assert "ABCD-1234-5678" not in str(body)


def test_engine_and_terms_endpoints():
    with TestClient(main.app) as http:
        engines = http.get("/api/v11/ocr/engines")
        plan = http.post(
            "/api/v11/ocr/engine-plan",
            json={
                "document_type": "mixed_pdf",
                "setup_budget": "high",
                "output_goal": "tables",
                "needs_layout": True,
                "needs_tables": True,
                "allow_gpu": True,
            },
        )
        terms = http.get("/api/v11/mortgage/terms")
    assert engines.status_code == 200
    assert plan.status_code == 200
    assert terms.status_code == 200
    assert engines.json()["engine_count"] >= 4
    assert plan.json()["primary"]["engine"] in {"docling", "paddleocr"}
    term_keys = {item["key"] for item in terms.json()["terms"]}
    assert {"contract_rate", "contract_discount", "interest_rate_differential"} <= term_keys


def test_review_session_http_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ocr_review_sessions", OCRReviewSessionStore(tmp_path / "sessions.sqlite3"))
    with TestClient(main.app) as http:
        created = http.post(
            "/api/v11/ocr/review-sessions",
            json={
                **page_payload(),
                "borrower_alias": "Client A",
                "actor": "api-test",
                "expires_days": 30,
            },
        )
        assert created.status_code == 201, created.text
        session = created.json()
        token = session["access_token"]
        sid = session["session_id"]
        assert session["status"] == "review_required"
        fetched = http.get(f"/api/v11/ocr/review-sessions/{sid}", headers=token_headers(token))
        assert fetched.status_code == 200, fetched.text
        corrected = http.post(
            f"/api/v11/ocr/review-sessions/{sid}/corrections",
            headers=token_headers(token),
            json={"corrections": {"offered_rate": "4.99"}, "actor": "reviewer"},
        )
        assert corrected.status_code == 200, corrected.text
        approvals = [
            {"field": "balance", "decision": "approved"},
            {"field": "offered_rate", "decision": "approved"},
            {"field": "amortization_months", "decision": "approved"},
            {"field": "maturity_date", "decision": "approved"},
        ]
        decided = http.post(
            f"/api/v11/ocr/review-sessions/{sid}/decisions",
            headers=token_headers(token),
            json={"decisions": approvals, "actor": "reviewer"},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "ready_for_prefill"
        finalized = http.post(
            f"/api/v11/ocr/review-sessions/{sid}/finalize",
            headers=token_headers(token),
            json={"actor": "reviewer", "note": "done"},
        )
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["status"] == "completed"
        audit = http.get(f"/api/v11/ocr/review-sessions/{sid}/audit", headers=token_headers(token))
        export = http.get(f"/api/v11/ocr/review-sessions/{sid}/export", headers=token_headers(token))
    assert audit.status_code == 200
    assert audit.json()["event_count"] >= 4
    assert export.status_code == 200
    assert export.json()["raw_ocr_stored"] is False
    assert "ABCD-1234-5678" not in str(export.json())


def test_review_session_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ocr_review_sessions", OCRReviewSessionStore(tmp_path / "sessions.sqlite3"))
    with TestClient(main.app) as http:
        created = http.post("/api/v11/ocr/review-sessions", json=page_payload())
        sid = created.json()["session_id"]
        missing = http.get(f"/api/v11/ocr/review-sessions/{sid}")
        wrong = http.get(f"/api/v11/ocr/review-sessions/{sid}", headers=token_headers("wrong"))
    assert missing.status_code == 403
    assert wrong.status_code == 403


def test_review_session_finalize_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ocr_review_sessions", OCRReviewSessionStore(tmp_path / "sessions.sqlite3"))
    with TestClient(main.app) as http:
        created = http.post("/api/v11/ocr/review-sessions", json=page_payload())
        session = created.json()
        response = http.post(
            f"/api/v11/ocr/review-sessions/{session['session_id']}/finalize",
            headers=token_headers(session["access_token"]),
            json={"actor": "reviewer"},
        )
    assert response.status_code == 409
    assert "blocking gates" in response.text
