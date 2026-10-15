import fitz
import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ocr.semantic_evidence_v16 import DocumentSemanticAuditError
from renewal.ocr.semantic_pdf_v16 import audit_semantic_pdf


TEXT = """Original mortgage
Mortgage date: 2022-03-01
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Term: 5 years
Maturity date: 2027-03-01
Renewal offer
Renewal rate: 5.49%
Balance: $480,000.00
Amortization: 20 years
Intrest rate differental applies if discharged early.
"""


def body(text=TEXT, **overrides):
    return {
        "pages": [{"page_number": 1, "text": text, "mean_confidence": 0.95}],
        "filename": "mortgage.txt", "as_of": "2026-10-14", **overrides,
    }


def pdf_bytes(text=TEXT, pages=1, encrypted=False):
    document = fitz.open()
    try:
        for _ in range(pages):
            page = document.new_page(height=1200)
            page.insert_text((40, 40), text, fontsize=10)
        options = {"encryption": fitz.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "reader"} if encrypted else {}
        return document.tobytes(**options)
    finally:
        document.close()


@pytest.fixture
def client():
    with TestClient(app) as http:
        yield http


def test_semantic_api_returns_scoped_evidence_and_date(client):
    response = client.post("/api/v16/ocr/semantic-audit", json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["provider"] == "mortgage-document-semantic-auditor-v16"
    assert result["as_of"] == "2026-10-14"
    assert result["facts"]["original.contract_rate"]["value"] == 4.39
    assert result["facts"]["renewal.offered_rate"]["value"] == 5.49
    assert response.headers["cache-control"] == "no-store"
    assert result["raw_ocr_stored"] is False


def test_api_preserves_typo_clause_and_conflict_evidence(client):
    response = client.post("/api/v16/ocr/semantic-audit", json=body(TEXT + "\nOriginal contract rate: 4.89%"))
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["status"] == "conflict"
    assert result["facts"]["original.contract_rate"]["value"] is None
    assert any(item["topic"] == "ird" and item["assertion"] == "conditional" for item in result["clauses"])


def test_api_accepts_scoped_correction_without_changing_renewal(client):
    response = client.post("/api/v16/ocr/semantic-audit", json=body(corrections={"original.contract_rate": 4.19}))
    assert response.status_code == 200, response.text
    facts = response.json()["facts"]
    assert facts["original.contract_rate"]["source"] == "reviewer"
    assert facts["original.contract_rate"]["value"] == 4.19
    assert facts["renewal.offered_rate"]["value"] == 5.49


@pytest.mark.parametrize("overrides", [
    {"pages": []}, {"pages": [{"text": ""}]}, {"pages": [{"text": "x", "page_number": 0}]},
    {"pages": [{"text": "x", "mean_confidence": 1.1}]}, {"as_of": "not-a-date"},
    {"min_confidence": 2}, {"corrections": {"contract_rate": 4.39}},
    {"corrections": {"original.mortgage_start_date": "03/04/2022"}},
    {"pages": [{"page_number": 1, "text": "a"}, {"page_number": 1, "text": "b"}]},
])
def test_api_rejects_invalid_audit_payloads(client, overrides):
    response = client.post("/api/v16/ocr/semantic-audit", json=body(**overrides))
    assert response.status_code == 422
    assert "detail" in response.json()


def test_api_threshold_prevents_low_confidence_math(client):
    response = client.post("/api/v16/ocr/semantic-audit", json=body(
        min_confidence=0.99,
    ))
    assert response.status_code == 200
    fact = response.json()["facts"]["original.contract_rate"]
    assert fact["status"] == "unreadable"
    assert fact["value"] is None


def test_pdf_endpoint_reads_searchable_pages(client):
    response = client.post("/api/v16/ocr/semantic-audit/pdf", files={
        "file": ("mortgage.pdf", pdf_bytes(), "application/pdf"),
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["filename"] == "mortgage.pdf"
    assert result["facts"]["original.contract_rate"]["value"] == 4.39
    assert len(result["pages"]) == 1


def test_pdf_audit_does_not_stop_at_short_preview_length():
    # More than 2,600 characters before the rate; every line is still on-page.
    text = ("Reference note about the mortgage agreement.\n" * 65) + "Original contract rate: 4.39%"
    result = audit_semantic_pdf(pdf_bytes(text))
    assert result["facts"]["original.contract_rate"]["value"] == 4.39
    assert result["pages"][0]["text_length"] > 2600


@pytest.mark.parametrize("data,error", [
    (b"not pdf", "valid PDF"), (b"%PDF-invalid", "open"),
    (b"%PDF-" + b"x" * (16 * 1024 * 1024), "15 MB"),
], ids=["invalid-header", "malformed-pdf", "oversized-pdf"])
def test_invalid_pdf_bytes_raise_domain_error(data, error):
    with pytest.raises(DocumentSemanticAuditError, match=error):
        audit_semantic_pdf(data)


def test_image_only_pdf_requests_ocr_instead_of_claiming_success():
    with pytest.raises(DocumentSemanticAuditError, match="OCR"):
        audit_semantic_pdf(pdf_bytes(""))


def test_password_protected_pdf_is_rejected():
    with pytest.raises(DocumentSemanticAuditError, match="unlocked"):
        audit_semantic_pdf(pdf_bytes(encrypted=True))


def test_pdf_page_limit_is_enforced():
    with pytest.raises(DocumentSemanticAuditError, match="16 pages"):
        audit_semantic_pdf(pdf_bytes(pages=17))


def test_pdf_endpoint_rejects_wrong_media_type(client):
    response = client.post("/api/v16/ocr/semantic-audit/pdf", files={
        "file": ("mortgage.png", b"not a pdf", "image/png"),
    })
    assert response.status_code == 415


def test_pdf_endpoint_rejects_unreadable_file(client):
    response = client.post("/api/v16/ocr/semantic-audit/pdf", files={
        "file": ("mortgage.pdf", b"%PDF-invalid", "application/pdf"),
    })
    assert response.status_code == 422


def test_pdf_endpoint_rejects_oversized_file(client):
    response = client.post("/api/v16/ocr/semantic-audit/pdf", files={
        "file": ("mortgage.pdf", b"%PDF-" + b"x" * (16 * 1024 * 1024), "application/pdf"),
    })
    assert response.status_code == 413


def test_openapi_includes_both_v16_audit_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v16/ocr/semantic-audit" in paths
    assert "/api/v16/ocr/semantic-audit/pdf" in paths
