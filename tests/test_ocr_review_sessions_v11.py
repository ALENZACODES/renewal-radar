import sqlite3

import pytest

from renewal.ocr.review_sessions import (
    OCRReviewAccessDenied,
    OCRReviewConflict,
    OCRReviewSessionError,
    OCRReviewSessionStore,
    quality_gates,
)


SAMPLE_TEXT = """
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
Interest rate differential applies if the mortgage is discharged early.
"""


def pages(text=SAMPLE_TEXT):
    return [{"page_number": 1, "text": text, "mean_confidence": 0.92}]


def store(tmp_path):
    return OCRReviewSessionStore(tmp_path / "review-sessions.sqlite3")


def create(store):
    return store.create_session(
        pages(),
        filename="renewal.txt",
        borrower_alias="Client A",
        actor="tester",
        expires_days=30,
    )


def required_approvals(session):
    fields = session["extraction"]["fields"]
    return [
        {"field": key, "decision": "approved"}
        for key in ("balance", "offered_rate", "amortization_months", "maturity_date")
        if key in fields
    ]


def test_create_session_stores_sanitized_extraction_not_raw_text(tmp_path):
    db = store(tmp_path)
    session = create(db)
    assert session["status"] == "review_required"
    assert session["borrower_alias"] == "Client A"
    assert session["raw_ocr_stored"] is False
    assert session["token_returned_after_create"] is True
    assert session["access_token"]
    assert "ABCD-1234-5678" not in str(session)
    with sqlite3.connect(tmp_path / "review-sessions.sqlite3") as conn:
        payload = conn.execute("SELECT extraction_json FROM ocr_review_sessions").fetchone()[0]
    assert "ABCD-1234-5678" not in payload
    assert SAMPLE_TEXT.strip() not in payload
    assert "[account-ref]" in payload


def test_get_session_requires_correct_token(tmp_path):
    db = store(tmp_path)
    session = create(db)
    with pytest.raises(OCRReviewAccessDenied):
        db.get_session(session["session_id"], "wrong-token")
    fetched = db.get_session(session["session_id"], session["access_token"])
    assert fetched["session_id"] == session["session_id"]
    assert "access_token" not in fetched
    assert fetched["token_returned_after_create"] is False


def test_apply_corrections_updates_fields_and_audit(tmp_path):
    db = store(tmp_path)
    session = create(db)
    corrected = db.apply_corrections(
        session["session_id"],
        session["access_token"],
        {"offered_rate": "4.99", "maturity_date": "March 1 2027"},
        actor="reviewer",
        note="Checked against the lender portal",
    )
    fields = corrected["extraction"]["fields"]
    assert fields["offered_rate"]["value"] == 4.99
    assert fields["offered_rate"]["source"] == "manual_review"
    assert corrected["extraction"]["manual_corrections"][-1]["actor"] == "reviewer"
    audit = db.audit_events(session["session_id"], session["access_token"])
    assert audit["event_count"] >= 2
    assert any(event["action"] == "corrections_applied" for event in audit["events"])


def test_approving_required_fields_allows_finalize(tmp_path):
    db = store(tmp_path)
    session = create(db)
    approved = db.record_decisions(
        session["session_id"],
        session["access_token"],
        required_approvals(session),
        actor="reviewer",
        note="Verified against source document",
    )
    assert approved["status"] == "ready_for_prefill"
    assert not approved["blocking_gates"]
    finalized = db.finalize_session(
        session["session_id"],
        session["access_token"],
        actor="reviewer",
        note="Ready for comparison prefill",
    )
    assert finalized["status"] == "completed"
    assert finalized["finalized_at"]


def test_finalize_before_required_approval_is_blocked(tmp_path):
    db = store(tmp_path)
    session = create(db)
    with pytest.raises(OCRReviewConflict) as caught:
        db.finalize_session(session["session_id"], session["access_token"])
    assert "required_fields_approved" in str(caught.value)


def test_rejected_field_creates_needs_rework_and_blocks_finalize(tmp_path):
    db = store(tmp_path)
    session = create(db)
    rejected = db.record_decisions(
        session["session_id"],
        session["access_token"],
        [{"field": "offered_rate", "decision": "rejected", "reason": "The OCR read the wrong offer."}],
    )
    assert rejected["status"] == "needs_rework"
    assert any(gate["gate"] == "no_rejected_fields" for gate in rejected["blocking_gates"])
    with pytest.raises(OCRReviewConflict):
        db.finalize_session(session["session_id"], session["access_token"])


def test_decision_validation(tmp_path):
    db = store(tmp_path)
    session = create(db)
    with pytest.raises(OCRReviewSessionError):
        db.record_decisions(session["session_id"], session["access_token"], [])
    with pytest.raises(OCRReviewSessionError):
        db.record_decisions(
            session["session_id"],
            session["access_token"],
            [{"field": "not_a_field", "decision": "approved"}],
        )
    with pytest.raises(OCRReviewSessionError):
        db.record_decisions(
            session["session_id"],
            session["access_token"],
            [{"field": "offered_rate", "decision": "needs_followup"}],
        )


def test_corrections_validation(tmp_path):
    db = store(tmp_path)
    session = create(db)
    with pytest.raises(OCRReviewSessionError):
        db.apply_corrections(session["session_id"], session["access_token"], {})
    with pytest.raises(Exception):
        db.apply_corrections(
            session["session_id"],
            session["access_token"],
            {"bank_password": "nope"},
        )


def test_export_packet_is_privacy_safe_and_digestable(tmp_path):
    db = store(tmp_path)
    session = create(db)
    db.record_decisions(
        session["session_id"],
        session["access_token"],
        required_approvals(session),
        actor="reviewer",
    )
    export = db.export_packet(session["session_id"], session["access_token"])
    assert export["raw_ocr_stored"] is False
    assert export["audit_digest"]
    assert export["audit_event_count"] >= 2
    assert "ABCD-1234-5678" not in str(export)
    assert SAMPLE_TEXT.strip() not in str(export)


def test_quality_gates_explain_missing_and_rejected_states():
    extraction = {
        "fields": {"balance": {"display_value": "480000.00"}},
        "pages": [{"page_number": 1, "text_sha256": "abc"}],
        "review_packet": [{"field": "offered_rate", "blocking": True}],
    }
    gates = quality_gates(extraction, [{"field": "balance", "decision": "rejected"}])
    names = {gate["gate"]: gate for gate in gates}
    assert names["required_fields_present"]["blocking"] is True
    assert names["no_rejected_fields"]["blocking"] is True
