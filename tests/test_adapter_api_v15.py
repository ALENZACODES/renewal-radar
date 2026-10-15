from fastapi.testclient import TestClient

from renewal.main import app


MORTGAGE_TEXT = """
Maple Bank Mortgage Renewal Agreement
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
"""


def marker_body(text=MORTGAGE_TEXT):
    return {
        "adapter": "marker",
        "payload": {
            "provider": "marker",
            "markdown": text,
            "chunks": [
                {"page": 1, "text": "Penalty: interest rate differential and three months interest.", "type": "clause"}
            ],
            "blocks": [{"page": 1, "type": "table", "rows": [["Balance", "$480,000.00"], ["Rate", "5.49%"]]}],
        },
    }


def paddle_body():
    return {
        "adapter": "paddleocr",
        "payload": {
            "provider": "paddleocr",
            "ocr_result": [
                [[[0, 0], [500, 0], [500, 20], [0, 20]], [line, 0.93]]
                for line in MORTGAGE_TEXT.splitlines()
                if line.strip()
            ],
        },
    }


def test_adapter_normalize_endpoint_returns_pages_and_quality():
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-normalize", json=paddle_body())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "adapter-output-normalizer-v15"
    assert body["adapter"] == "paddleocr"
    assert body["span_count"] >= 8
    assert body["quality"]["has_money"] is True
    assert body["quality"]["has_rate"] is True
    assert body["ocr_pages"]


def test_adapter_preview_endpoint_returns_validation_summary():
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-preview", json=marker_body())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "adapter-payload-preview-v15"
    assert body["summary"]["span_count"] >= 1
    assert body["summary"]["valid_for_contract_review"] is True
    assert body["quality"]["has_penalty_language"] is True


def test_adapter_evaluate_endpoint_runs_full_contract_stack():
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-evaluate", json=marker_body())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "adapter-payload-evaluation-v15"
    assert body["preview"]["provider"] == "adapter-payload-preview-v15"
    assert body["validation"]["provider"] == "normalized-packet-validator-v15"
    assert body["evaluation"]["provider"] == "adapter-quality-harness-v15"
    assert body["evaluation"]["brief_summary"]["provider"] == "deterministic-contract-intelligence-v12"
    assert body["evaluation"]["math_summary"]["provider"] == "canadian-contract-math-audit-v13"
    assert body["evaluation"]["dependency_summary"]["provider"] == "optional-dependency-adapter-plan-v14"


def test_adapter_evaluate_endpoint_blocks_thin_payload_with_next_actions():
    with TestClient(app) as http:
        response = http.post(
            "/api/v15/ocr/adapter-evaluate",
            json=marker_body("Contract rate: 4.39%\nPosted rate: 5.69%"),
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["evaluation"]["score"]["level"] == "blocked"
    assert body["evaluation"]["next_actions"]
    assert any(action["id"] == "action-field-balance" for action in body["evaluation"]["next_actions"])


def test_adapter_normalize_endpoint_rejects_unknown_payloads():
    with TestClient(app) as http:
        response = http.post(
            "/api/v15/ocr/adapter-normalize",
            json={"payload": {"unknown": "shape"}},
        )
    assert response.status_code == 422


def test_adapter_workbench_endpoint_compares_candidates_and_selects_pages():
    body = {
        "candidates": [
            marker_body(),
            paddle_body(),
            marker_body("Contract rate: 4.39%\nPosted rate: 5.69%"),
        ]
    }
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-workbench", json=body)
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["provider"] == "adapter-workbench-report-v15"
    assert result["workbench"]["candidate_count"] == 3
    assert result["workbench"]["evaluated_count"] == 3
    assert result["workbench"]["selected_candidate_id"]
    assert result["workbench"]["selected_ocr_pages"]
    assert result["consensus"]["provider"] == "adapter-consensus-v15"
    assert result["merged_pages"]


def test_adapter_workbench_endpoint_rejects_empty_candidates():
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-workbench", json={"candidates": []})
    assert response.status_code == 422


def test_adapter_reconcile_endpoint_returns_field_decisions():
    body = {
        "candidates": [
            marker_body(),
            paddle_body(),
            marker_body("Contract rate: 4.39%\nPosted rate: 5.69%"),
        ]
    }
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-reconcile", json=body)
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["provider"] == "adapter-reconciliation-report-v15"
    assert result["workbench"]["evaluated_count"] == 3
    assert result["reconciliation"]["provider"] == "adapter-field-reconciliation-v15"
    assert result["reconciliation"]["summary"]["field_count"] >= 1
    assert result["reviewer_decisions"]
    assert result["ready_without_review"] is False


def test_adapter_reconcile_endpoint_rejects_empty_candidates():
    with TestClient(app) as http:
        response = http.post("/api/v15/ocr/adapter-reconcile", json={"candidates": []})
    assert response.status_code == 422


def test_adapter_benchmark_endpoint_runs_filtered_suite():
    with TestClient(app) as http:
        response = http.post(
            "/api/v15/ocr/adapter-benchmark",
            json={"adapters": ["marker"], "include_candidate_sets": False},
        )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["provider"] == "adapter-benchmark-suite-v15"
    assert result["summary"]["provider"] == "adapter-benchmark-summary-v15"
    assert result["summary"]["case_count"] == 2
    assert result["summary"]["passed_count"] == 2
    assert result["results"]
    assert result["actions"]


def test_adapter_benchmark_endpoint_rejects_unknown_filter():
    with TestClient(app) as http:
        response = http.post(
            "/api/v15/ocr/adapter-benchmark",
            json={"adapters": ["not-real"], "include_candidate_sets": False},
        )
    assert response.status_code == 422
