import pytest

from renewal.ocr.adapter_reconciliation_v15 import (
    AdapterReconciliationError,
    FieldVote,
    build_reconciliation_report,
    reconcile_field,
    reconcile_votes,
    reviewer_decisions_from_reconciliation,
)


MORTGAGE_TEXT = """
Mortgage date: 2022-03-01
Outstanding mortgage balance at renewal: $480,000.00
Contract rate: 4.39%
Posted rate: 5.69%
Contract discount: 1.30%
Renewal interest rate: 5.49%
Remaining amortization period: 240 months
Maturity date: 2027-03-01
Interest rate differential applies if discharged early.
"""


def marker_payload(text=MORTGAGE_TEXT):
    return {"provider": "marker", "markdown": text}


def paddle_payload(text=MORTGAGE_TEXT):
    return {
        "provider": "paddleocr",
        "ocr_result": [
            [[[0, index * 10], [500, index * 10], [500, index * 10 + 8], [0, index * 10 + 8]], [line, 0.93]]
            for index, line in enumerate(text.splitlines(), 1)
            if line.strip()
        ],
    }


def vote(field, value, candidate="candidate-001-marker", adapter="marker", confidence="high"):
    return FieldVote(
        field=field,
        value=value,
        display_value=str(value),
        candidate_id=candidate,
        adapter=adapter,
        confidence=confidence,
        evidence=(f"field:{field}",),
    )


def test_reconcile_field_marks_consensus_when_candidates_agree():
    result = reconcile_field(
        "contract_rate",
        [
            vote("contract_rate", 4.39, "candidate-001-marker", "marker"),
            vote("contract_rate", "4.39%", "candidate-002-paddleocr", "paddleocr"),
        ],
    )
    public = result.public()

    assert public["status"] == "consensus"
    assert public["confidence"] == "high"
    assert public["distinct_value_count"] == 1
    assert len(public["candidate_ids"]) == 2


def test_reconcile_field_marks_conflict_when_values_disagree():
    result = reconcile_field(
        "posted_rate",
        [
            vote("posted_rate", 5.69, "candidate-001-marker", "marker"),
            vote("posted_rate", 5.19, "candidate-002-paddleocr", "paddleocr"),
        ],
    )

    assert result.status == "conflict"
    assert result.confidence == "low"
    assert result.distinct_value_count == 2
    assert "disagreed" in result.note


def test_reconcile_field_marks_missing_without_votes():
    result = reconcile_field("balance", [])
    assert result.status == "missing"
    assert result.selected_value is None
    assert result.vote_count == 0


def test_reconcile_votes_summarizes_consensus_conflicts_and_missing_fields():
    reconciliation = reconcile_votes(
        [
            vote("contract_rate", 4.39, "candidate-001-marker", "marker"),
            vote("contract_rate", "4.39%", "candidate-002-paddleocr", "paddleocr"),
            vote("posted_rate", 5.69, "candidate-001-marker", "marker"),
            vote("posted_rate", 5.19, "candidate-002-paddleocr", "paddleocr"),
        ]
    )

    assert reconciliation["provider"] == "adapter-field-reconciliation-v15"
    assert reconciliation["summary"]["consensus_count"] >= 1
    assert reconciliation["summary"]["conflict_count"] >= 1
    assert reconciliation["summary"]["missing_count"] >= 1
    assert reconciliation["review_required"] is True


def test_reviewer_decisions_map_statuses_to_actions():
    reconciliation = reconcile_votes(
        [
            vote("contract_rate", 4.39, "candidate-001-marker", "marker"),
            vote("contract_rate", "4.39%", "candidate-002-paddleocr", "paddleocr"),
            vote("posted_rate", 5.69, "candidate-001-marker", "marker"),
            vote("posted_rate", 5.19, "candidate-002-paddleocr", "paddleocr"),
        ]
    )
    decisions = reviewer_decisions_from_reconciliation(reconciliation)
    by_field = {decision["field"]: decision for decision in decisions}

    assert by_field["contract_rate"]["action"] == "verify_consensus"
    assert by_field["posted_rate"]["action"] == "resolve_conflict"
    assert by_field["balance"]["action"] == "collect_missing"


def test_build_reconciliation_report_compares_real_adapter_candidates():
    report = build_reconciliation_report(
        [
            {"adapter": "marker", "payload": marker_payload()},
            {"adapter": "paddleocr", "payload": paddle_payload()},
        ]
    )

    assert report["provider"] == "adapter-reconciliation-report-v15"
    assert report["workbench"]["evaluated_count"] == 2
    assert report["reconciliation"]["summary"]["vote_count"] >= 1
    assert report["reviewer_decisions"]
    assert report["ready_without_review"] is False


def test_build_reconciliation_report_detects_conflicting_adapter_values():
    conflict_text = MORTGAGE_TEXT.replace("Posted rate: 5.69%", "Posted rate: 5.19%")
    report = build_reconciliation_report(
        [
            {"adapter": "marker", "payload": marker_payload()},
            {"adapter": "paddleocr", "payload": paddle_payload(conflict_text)},
        ]
    )
    fields = {field["field"]: field for field in report["reconciliation"]["fields"]}

    assert fields["posted_rate"]["status"] in {"conflict", "single_source"}
    assert report["reviewer_decisions"]


def test_build_reconciliation_report_requires_candidates():
    with pytest.raises(AdapterReconciliationError):
        build_reconciliation_report([])
