from fastapi.testclient import TestClient

from renewal.main import app


OCR_TEXT = """
Lender: Maple Bank
Mortgage number: ABCD-1234-5678
Outstanding mortgage balance at renewal: $480,000.00
Current interest rate: 4.19%
Renewal interest rate: 5.49%
Renewal term: 36 months
Remaining amortization period: 228 months
Maturity date: 2027-03-01
Payment amount: $3,378.66
Payment frequency: monthly
"""


def test_ocr_fields_endpoint():
    with TestClient(app) as http:
        response = http.post(
            "/api/v10/ocr/fields",
            json={
                "filename": "sample-ocr.txt",
                "pages": [{"page_number": 1, "text": OCR_TEXT, "mean_confidence": 0.91}],
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fields"]["balance"]["value"] == 480000.0
    assert body["fields"]["offered_rate"]["value"] == 5.49
    assert body["fields"]["mortgage_reference"]["value"] == "****5678"
    assert body["review_status"] == "ready"
    assert "ABCD-1234-5678" not in str(body)


def test_ocr_review_endpoint_applies_corrections():
    with TestClient(app) as http:
        response = http.post(
            "/api/v10/ocr/review",
            json={
                "pages": [{"text": OCR_TEXT, "mean_confidence": 0.8}],
                "corrections": {"offered_rate": "4.99", "maturity_date": "March 1 2027"},
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fields"]["offered_rate"]["value"] == 4.99
    assert body["fields"]["offered_rate"]["source"] == "manual_review"
    assert body["review_summary"]["manual_correction_count"] == 2
    assert body["review_summary"]["can_prefill_mortgage_form"]


def test_ocr_fields_rejects_too_many_pages():
    with TestClient(app) as http:
        response = http.post(
            "/api/v10/ocr/fields",
            json={"pages": [{"text": "x"} for _ in range(17)]},
        )
    assert response.status_code == 422


def test_ocr_review_rejects_unknown_correction():
    with TestClient(app) as http:
        response = http.post(
            "/api/v10/ocr/review",
            json={
                "pages": [{"text": OCR_TEXT}],
                "corrections": {"bank_password": "never"},
            },
        )
    assert response.status_code == 422
    assert "Unknown correction field" in response.text


def test_ocr_fields_missing_required_reports_blocked():
    with TestClient(app) as http:
        response = http.post(
            "/api/v10/ocr/fields",
            json={"pages": [{"text": "Payment amount: $3000.00"}]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "blocked"
    assert "balance" in body["missing_required"]

