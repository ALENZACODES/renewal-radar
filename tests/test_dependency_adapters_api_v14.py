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


def payload(text=OCR_TEXT, filename="renewal-contract.pdf"):
    return {
        "filename": filename,
        "question": "Which optional OCR/document adapter is best?",
        "pages": [{"page_number": 1, "text": text, "mean_confidence": 0.93}],
    }


def test_optional_dependencies_endpoint_lists_built_in_dependency_profiles():
    with TestClient(app) as http:
        response = http.get("/api/v14/ocr/optional-dependencies")
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {item["key"] for item in body["dependencies"]}

    assert body["provider"] == "optional-ocr-dependencies-v14"
    assert body["dependency_count"] == 6
    assert {"docling", "unstructured", "paddleocr", "surya", "marker", "olmocr"} <= keys
    assert any(line.startswith("docling>=2.119") for line in body["optional_requirements"])
    assert "not required runtime dependencies" in body["notice"]


def test_dependency_plan_endpoint_returns_ranked_profiles_and_input_contracts():
    with TestClient(app) as http:
        response = http.post("/api/v14/contract-intelligence/dependency-plan", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "optional-dependency-adapter-plan-v14"
    assert body["policy"]["base_app_requires_optional_dependencies"] is False
    assert body["policy"]["github_code_copied"] is False
    assert body["document_signals"]["is_pdf"] is True
    assert body["document_signals"]["has_rate_context"] is True
    assert body["document_signals"]["has_penalty_context"] is True
    assert body["ranked_profiles"]
    assert body["recommended_chain"]
    assert body["input_contracts"]
    assert body["dependency_status"]["docling"]["runtime_required"] is False
    assert "ABCD-1234-5678" not in str(body)


def test_dependency_plan_endpoint_keeps_thin_documents_on_manual_review_path():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v14/contract-intelligence/dependency-plan",
            json=payload(text=text, filename="thin.pdf"),
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["document_signals"]["has_required_missing"] is True
    assert "balance" in body["document_signals"]["missing_required"]
    assert any(item["key"] == "manual_reviewer_correction" for item in body["local_fallback_chain"])
    assert any(contract["privacy_controls"]["review_required_before_prefill"] for contract in body["input_contracts"])


def test_adapter_readiness_endpoint_returns_operator_gates_and_steps():
    with TestClient(app) as http:
        response = http.post("/api/v14/contract-intelligence/adapter-readiness", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "optional-adapter-readiness-report-v14"
    assert body["ready_to_run_base_app"] is True
    assert body["can_prefill_without_manual_review"] is False
    assert body["gates"]
    assert body["execution_steps"]
    assert body["summary"]["recommended_profile_count"] >= 1
    assert body["operator_notes"]


def test_adapter_readiness_endpoint_blocks_missing_field_documents():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v14/contract-intelligence/adapter-readiness",
            json=payload(text=text, filename="thin.pdf"),
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["ready_to_run_base_app"] is True
    assert body["summary"]["high_blocker_count"] >= 1
    assert any(gate["id"] == "missing-fields" and gate["status"] == "blocked" for gate in body["gates"])
    assert any(blocker["id"] == "missing-fields" for blocker in body["blockers"])
