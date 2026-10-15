from fastapi.testclient import TestClient

from renewal.main import app


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
The penalty may be the greater of three months interest or the interest rate differential.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def payload(question=None, text=OCR_TEXT):
    body = {
        "filename": "renewal-contract.txt",
        "pages": [{"page_number": 1, "text": text, "mean_confidence": 0.93}],
    }
    if question is not None:
        body["question"] = question
    return body


def test_contract_sources_endpoint():
    with TestClient(app) as http:
        response = http.get("/api/v12/contract-intelligence/sources")
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {item["key"] for item in body["sources"]}
    assert {"docling", "unstructured", "presidio", "cuad"} <= keys
    assert body["provider"] == "contract-intelligence-source-map-v12"
    assert body["verified_date"] == "2026-10-13"


def test_contract_brief_endpoint_returns_evidence_and_answer():
    with TestClient(app) as http:
        response = http.post(
            "/api/v12/contract-intelligence/brief",
            json=payload("Explain the contract discount"),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "deterministic-contract-intelligence-v12"
    assert body["classification"]["type"] == "renewal_offer"
    assert body["evidence_graph"]["summary"]["has_rate_context"] is True
    assert body["risk_assessment"]["risk_count"] >= 1
    assert body["answer"]["topic"] == "posted_rate_discount"
    assert "calculation:contract_discount" in body["answer"]["evidence"]
    assert "ABCD-1234-5678" not in str(body)


def test_contract_answer_endpoint_returns_compact_answer_package():
    with TestClient(app) as http:
        response = http.post(
            "/api/v12/contract-intelligence/answer",
            json=payload("What is my IRD penalty?"),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"answer", "evidence_graph", "risk_assessment", "readiness"}
    assert body["answer"]["topic"] == "interest_rate_differential"
    assert "written payout statement" in body["answer"]["answer"]
    assert body["evidence_graph"]["summary"]["has_penalty_context"] is True


def test_contract_answer_endpoint_requires_question():
    with TestClient(app) as http:
        response = http.post("/api/v12/contract-intelligence/answer", json=payload())
    assert response.status_code == 422
    assert "Question is required" in response.text


def test_contract_brief_endpoint_surfaces_missing_fields():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%\nContract discount: 1.30%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v12/contract-intelligence/brief",
            json=payload("What is risky?", text=text),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["readiness"]["state"] == "blocked"
    assert "balance" in body["readiness"]["missing_required"]
    assert any(risk["id"] == "missing-required-fields" for risk in body["risk_assessment"]["risks"])


def test_contract_playbook_endpoint_returns_operational_checklist():
    with TestClient(app) as http:
        response = http.post(
            "/api/v12/contract-intelligence/playbook",
            json=payload("Explain the contract discount"),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "contract-review-playbook-v12"
    assert body["checklist"]["task_count"] == len(body["tasks"])
    assert body["prefill"]["can_prefill"] is True
    assert body["question_answer"]["topic"] == "posted_rate_discount"
    assert body["manual_review_gates"]["required_approvals"]
    assert any(row["field"] == "contract_discount" for row in body["field_review_matrix"])
    assert "ABCD-1234-5678" not in str(body)


def test_contract_playbook_endpoint_blocks_thin_documents():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%\nContract discount: 1.30%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v12/contract-intelligence/playbook",
            json=payload("What is missing?", text=text),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["readiness"]["state"] == "blocked"
    assert body["prefill"]["can_prefill"] is False
    assert body["checklist"]["critical_task_count"] >= 1
    assert any(task["id"].startswith("missing-") for task in body["tasks"])
