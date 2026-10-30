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


def payload(text=OCR_TEXT, question="Explain the contract discount and penalty"):
    return {
        "filename": "renewal-contract.txt",
        "question": question,
        "pages": [{"page_number": 1, "text": text, "mean_confidence": 0.93}],
    }


def test_research_sources_endpoint_is_dependency_free():
    with TestClient(app) as http:
        response = http.get("/api/v13/contract-intelligence/research-sources")
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {source["key"] for source in body["sources"]}

    assert body["provider"] == "contract-research-radar-v13"
    assert body["runtime_dependency_count"] == 0
    assert {"docling", "paddleocr", "olmocr", "marker", "surya", "fcac"} <= keys
    assert body["policy"]["imports_external_projects"] is False


def test_math_audit_endpoint_returns_formula_walkthroughs_and_penalty_scenarios():
    with TestClient(app) as http:
        response = http.post("/api/v13/contract-intelligence/math-audit", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()
    scenario_ids = {scenario["id"] for scenario in body["penalty_scenarios"]}
    formula_ids = {formula["id"] for formula in body["formula_walkthroughs"]}

    assert body["provider"] == "canadian-contract-math-audit-v13"
    assert "three-month-interest" in scenario_ids
    assert "posted-discount-ird" in scenario_ids
    assert "formula-contract-discount" in formula_ids
    assert "ask-payout-statement" in {prompt["id"] for prompt in body["disclosure_prompts"]}
    assert "ABCD-1234-5678" not in str(body)


def test_research_radar_endpoint_combines_sources_math_and_local_adapter_tasks():
    with TestClient(app) as http:
        response = http.post("/api/v13/contract-intelligence/research-radar", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()
    need_keys = {need["key"] for need in body["adapter_needs"]}
    task_ids = {task["id"] for task in body["in_house_adapter_tasks"]}

    assert body["provider"] == "no-dependency-contract-research-radar-v13"
    assert body["dependency_policy"]["new_pip_dependencies"] == []
    assert body["dependency_policy"]["runtime_external_imports"] == []
    assert body["dependency_policy"]["github_code_copied"] is False
    assert "rate_context_reasoning" in need_keys
    assert "penalty_language_review" in need_keys
    assert "adapter-penalty-review" in task_ids
    assert body["math_audit"]["provider"] == "canadian-contract-math-audit-v13"
    assert body["playbook_summary"]["task_count"] >= 1


def test_research_radar_endpoint_surfaces_missing_fields_on_thin_documents():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v13/contract-intelligence/research-radar",
            json=payload(text=text, question="What is missing?"),
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["adapter_needs"][0]["key"] == "required_field_recovery"
    assert body["math_audit"]["confidence"]["level"] == "low"
    assert body["playbook_summary"]["critical_task_count"] >= 1
    assert any(task["id"] == "adapter-required-field-recovery" for task in body["in_house_adapter_tasks"])


def test_lender_packet_endpoint_returns_safe_reviewer_packet():
    with TestClient(app) as http:
        response = http.post("/api/v13/contract-intelligence/lender-packet", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "lender-review-packet-v13"
    assert body["source_providers"]["brief"] == "deterministic-contract-intelligence-v12"
    assert body["source_providers"]["math_audit"] == "canadian-contract-math-audit-v13"
    assert body["dependency_policy"]["new_pip_dependencies"] == []
    assert body["snapshot"]["raw_ocr_stored"] is False
    assert body["lender_questions"]
    assert body["evidence_appendix"]["node_count"] >= 5
    assert body["signoff"]["can_send_to_lender"] is True
    assert "ABCD-1234-5678" not in str(body)


def test_lender_packet_endpoint_keeps_thin_documents_blocked():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%"
    with TestClient(app) as http:
        response = http.post(
            "/api/v13/contract-intelligence/lender-packet",
            json=payload(text=text, question="What should the lender confirm?"),
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["snapshot"]["readiness"]["state"] == "blocked"
    assert body["signoff"]["can_send_to_lender"] is False
    assert any(gate["status"] == "blocked" for gate in body["signoff"]["gates"])
