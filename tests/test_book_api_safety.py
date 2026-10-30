import json
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.broker import book_api, book_review
from renewal.ratewatch import history

DAY = "2026-10-15"
client = TestClient(app)


def deal(**changes):
    return {
        "deal_id": "API-1", "borrower": "Fictional Client", "lender": "TD",
        "rate_type": "fixed", "balance": 400000, "contract_rate": 6.5,
        "posted_rate": 8, "term_months": 60, "amort_months": 300,
        "closing_date": "2023-10-15", "maturity_date": "2028-10-15",
        **changes,
    }


def request(deals=None, **changes):
    return {"deals": [deal()] if deals is None else deals, "as_of": DAY, "target_rate": 4.4, **changes}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(book_review, "_board", lambda: {})
    history.save("P023", "2026-10-14", [
        (term, "fixed_closed", "posted", 7.0)
        for term in (6, 12, 24, 36, 48, 60, 72, 84, 120)
    ], "api")


@pytest.mark.parametrize("field,value", [
    ("term_months", -1),
    ("term_months", 9999),
    ("term_months", True),
    ("term_months", 12.5),
    ("amort_months", 0),
    ("amort_months", 481),
    ("amort_months", "forever"),
    ("amort_months", {}),
    ("balance", []),
    ("balance", {}),
    ("payment", True),
    ("contract_rate", []),
    ("discount", {}),
    ("borrower", {}),
    ("lender", 42),
    ("review_confirmed", "false"),
    ("review_confirmed", 1),
    ("evidence", []),
    ("issues", "not a list"),
])
def test_bad_nested_fields_receive_422(field, value):
    response = client.post("/api/broker/book/review", json=request([deal(**{field: value})]))
    assert response.status_code == 422


def test_unknown_nested_fields_are_not_silently_discarded():
    response = client.post("/api/broker/book/review", json=request([deal(secret_extra="not used")]))
    assert response.status_code == 422
    assert "unknown fields" in response.text


@pytest.mark.parametrize("changes", [
    {"as_of": "2999-01-01"},
    {"closed_from": "1900-01-01"},
    {"closed_from": "2026-12-01", "closed_to": "2026-01-01"},
    {"fees": -1},
    {"fees": 50001},
    {"new_term_months": 0},
    {"new_term_months": 121},
    {"target_rate": 99},
])
def test_review_window_and_assumptions_are_bounded(changes):
    assert client.post("/api/broker/book/review", json=request(**changes)).status_code == 422


def test_review_limit_is_explicit():
    payload = request([deal(deal_id=str(i)) for i in range(2001)])
    response = client.post("/api/broker/book/review", json=payload)
    assert response.status_code == 422
    assert "2000" in response.text


def test_capabilities_match_actual_limits():
    response = client.get("/api/broker/book/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["maximum_review_rows"] == 2000
    assert data["maximum_import_bytes"] == 20 * 1024 * 1024
    assert data["requires_ocr_confirmation"] is True
    assert data["stores_imported_deals"] is False
    assert "biweekly" in data["payment_frequencies"]
    assert "review_confirmed" in data["fields"]


def test_mapping_json_errors_are_handled_without_a_server_error():
    response = client.post("/api/broker/book/import",
                           files={"file": ("book.csv", b"Lender,Rate\nTD,5\n", "text/csv")},
                           data={"mapping": "{"})
    assert response.status_code == 422


@pytest.mark.parametrize("mapping", ['[]', '{"unknown":"Lender"}', '{"lender":3}'])
def test_mapping_shape_is_checked(mapping):
    response = client.post("/api/broker/book/import",
                           files={"file": ("book.csv", b"Lender,Rate\nTD,5\n", "text/csv")},
                           data={"mapping": mapping})
    assert response.status_code == 422


def test_explicit_date_order_is_available_through_the_api():
    source = b"Lender,Rate,Closing Date,Term,Current Balance\nTD,5,03/04/2024,5,400000\n"
    response = client.post("/api/broker/book/import",
                           files={"file": ("book.csv", source, "text/csv")},
                           data={"date_order": "day_first"})
    assert response.status_code == 200
    assert response.json()["deals"][0]["closing_date"] == "2024-04-03"


def test_invalid_date_order_is_not_ignored():
    response = client.post("/api/broker/book/import",
                           files={"file": ("book.csv", b"Lender,Rate\nTD,5\n", "text/csv")},
                           data={"date_order": "guess"})
    assert response.status_code == 422


def test_api_returns_reconcilable_financial_rows():
    response = client.post("/api/broker/book/review", json=request())
    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["net_benefit"] == row["economics"]["monthly"][-1]["net_after_costs"]
    assert row["horizon_months"] <= 60
    assert response.headers["cache-control"] == "no-store"


def test_json_import_and_review_do_not_log_borrower_data(caplog):
    marker = "FictionalPrivacyMarker"
    source = json.dumps([deal(borrower=marker)]).encode()
    imported = client.post("/api/broker/book/import",
                           files={"file": ("book.json", source, "application/json")})
    assert imported.status_code == 200
    response = client.post("/api/broker/book/review", json=request(imported.json()["deals"]))
    assert response.status_code == 200
    assert marker not in caplog.text
    assert imported.headers["cache-control"] == "no-store"


def test_exports_are_private_and_formula_safe():
    response = client.post("/api/broker/book/review.csv", json=request([deal(borrower="=1+1")]))
    assert response.status_code == 200
    assert "'=1+1" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]


def test_concurrent_review_capacity_returns_retryable_error(monkeypatch):
    class Full:
        def acquire(self, blocking=False):
            return False

        def release(self):
            raise AssertionError("unacquired review slot released")
    monkeypatch.setattr(book_api, "_review_slots", Full())
    response = client.post("/api/broker/book/review", json=request())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"


def test_review_slot_is_released_after_a_domain_error(monkeypatch):
    guard = Mock()
    guard.acquire.return_value = True
    monkeypatch.setattr(book_api, "_review_slots", guard)
    monkeypatch.setattr(book_review, "review_book", Mock(side_effect=ValueError("bad values")))
    response = client.post("/api/broker/book/review", json=request())
    assert response.status_code == 422
    guard.release.assert_called_once()


def test_ocr_errors_are_generic_and_do_not_echo_document_text(monkeypatch):
    from renewal.services import document_ocr_v17
    marker = "PrivateBorrowerErrorPayload"
    monkeypatch.setattr(document_ocr_v17, "read_mortgage_document", Mock(side_effect=ValueError(marker)))
    response = client.post("/api/broker/book/ocr", files={"files": ("scan.png", b"bad image", "image/png")})
    assert response.status_code == 200
    assert response.json()["deals"] == []
    assert response.json()["errors"]
    assert marker not in response.text


def test_ocr_cannot_select_an_arbitrary_engine_language():
    response = client.post("/api/broker/book/ocr",
                           files={"files": ("scan.png", b"bad image", "image/png")},
                           data={"language": "../unexpected"})
    assert response.status_code == 422


def test_ocr_issues_require_confirmation_before_review(monkeypatch):
    from renewal.services import document_ocr_v17
    monkeypatch.setattr(document_ocr_v17, "read_mortgage_document", lambda *a: {
        "fields": {
            "balance": {"value": 400000, "page": 1, "excerpt": "Balance"},
            "current_rate": {"value": 6.5, "page": 1, "excerpt": "Rate"},
            "term_months": {"value": 60, "page": 1, "excerpt": "Term"},
            "maturity_date": {"value": "2028-10-15", "page": 1, "excerpt": "Maturity"},
            "amortization_months": {"value": 300, "page": 1, "excerpt": "Amortization"},
        },
    })
    response = client.post("/api/broker/book/ocr",
                           files={"files": ("scan.png", b"fake fixture", "image/png")},
                           data={"lender": "TD", "closing_date": "2023-10-15"})
    assert response.status_code == 200
    imported = response.json()["deals"]
    assert imported[0]["source"] == "ocr"
    review = client.post("/api/broker/book/review", json=request(imported)).json()["results"][0]
    assert review["status"] == "needs_data"
    assert any(i["code"] == "ocr_unverified" for i in review["validation"])


@pytest.mark.parametrize("term", [0, -1, 999, 13])
def test_offer_term_is_bounded(term):
    assert client.get("/api/broker/book/offers", params={"term_months": term}).status_code == 422
