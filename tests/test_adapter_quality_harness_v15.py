import pytest

from renewal.ocr.adapter_output_normalizer_v15 import normalize_adapter_payload
from renewal.ocr.adapter_quality_harness_v15 import (
    AdapterQualityHarnessError,
    best_next_actions,
    evaluate_adapter_payload,
    evaluate_normalized_packet,
    evidence_quality_gates,
    field_coverage_gates,
    mortgage_reasoning_gates,
    score_gates,
)
from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.contract_math_v13 import build_contract_math_audit_from_brief
from renewal.ocr.contract_packet_v13 import build_lender_packet_from_brief
from renewal.ocr.dependency_adapters_v14 import build_dependency_adapter_plan_from_brief


MORTGAGE_TEXT = """
Maple Bank Mortgage Renewal Agreement
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


def marker_payload(text=MORTGAGE_TEXT):
    return {
        "provider": "marker",
        "markdown": text,
        "chunks": [
            {"page": 1, "text": "Penalty clause: interest rate differential and three months interest.", "type": "clause"},
        ],
        "blocks": [{"page": 1, "type": "table", "rows": [["Balance", "$480,000.00"], ["Rate", "5.49%"]]}],
    }


def thin_payload():
    return {
        "provider": "marker",
        "markdown": "Contract rate: 4.39%\nPosted rate: 5.69%",
    }


def brief_from_packet(packet):
    return create_contract_brief(packet["ocr_pages"], filename="adapter.txt")


def test_evidence_quality_gates_pass_for_complete_payload():
    packet = normalize_adapter_payload(marker_payload())
    gates = evidence_quality_gates(packet)
    by_id = {gate.id: gate for gate in gates}

    assert by_id["normalized-spans"].status == "pass"
    assert by_id["money-detected"].status == "pass"
    assert by_id["rate-detected"].status == "pass"
    assert by_id["low-confidence-lines"].status == "pass"


def test_evidence_quality_gates_review_low_confidence_lines():
    packet = normalize_adapter_payload(
        {
            "provider": "paddleocr",
            "ocr_result": [[[[0, 0], [100, 0], [100, 10], [0, 10]], ["Contract rate: 4.39%", 0.25]]],
        }
    )
    gates = evidence_quality_gates(packet)
    low = next(gate for gate in gates if gate.id == "low-confidence-lines")

    assert low.status == "review"
    assert low.severity == "medium"
    assert low.evidence


def test_field_coverage_gates_require_core_comparison_fields():
    complete = field_coverage_gates(brief_from_packet(normalize_adapter_payload(marker_payload())))
    complete_by_id = {gate.id: gate for gate in complete}
    thin = field_coverage_gates(brief_from_packet(normalize_adapter_payload(thin_payload())))
    thin_by_id = {gate.id: gate for gate in thin}

    assert complete_by_id["field-balance"].status == "pass"
    assert complete_by_id["field-offered_rate"].status == "pass"
    assert thin_by_id["field-balance"].status == "fail"
    assert thin_by_id["field-maturity_date"].status == "fail"
    assert thin_by_id["rate-context"].status == "pass"


def test_mortgage_reasoning_gates_capture_readiness_math_and_packet_status():
    packet = normalize_adapter_payload(marker_payload())
    brief = brief_from_packet(packet)
    math_audit = build_contract_math_audit_from_brief(brief)
    lender_packet = build_lender_packet_from_brief(brief)
    gates = mortgage_reasoning_gates(brief, math_audit, lender_packet)
    by_id = {gate.id: gate for gate in gates}

    assert by_id["brief-readiness"].status == "pass"
    assert by_id["math-confidence"].status == "pass"
    assert by_id["high-risks"].status == "pass"
    assert by_id["lender-packet"].status == "pass"


def test_score_gates_blocks_on_failed_required_fields():
    packet = normalize_adapter_payload(thin_payload())
    brief = brief_from_packet(packet)
    gates = evidence_quality_gates(packet) + field_coverage_gates(brief)
    score = score_gates(gates)

    assert score["level"] == "blocked"
    assert score["fail_count"] >= 1
    assert score["score"] < 100


def test_best_next_actions_include_missing_fields_and_optional_profiles():
    packet = normalize_adapter_payload(thin_payload())
    brief = brief_from_packet(packet)
    plan = build_dependency_adapter_plan_from_brief(brief)
    gates = evidence_quality_gates(packet) + field_coverage_gates(brief)
    actions = best_next_actions(gates, plan)
    action_ids = {action["id"] for action in actions}

    assert "action-field-balance" in action_ids
    assert any(action["id"].startswith("action-optional-") for action in actions)


def test_evaluate_normalized_packet_returns_scorecard_and_next_actions():
    packet = normalize_adapter_payload(marker_payload())
    result = evaluate_normalized_packet(packet)

    assert result["provider"] == "adapter-quality-harness-v15"
    assert result["adapter"] == "marker"
    assert result["score"]["level"] in {"reviewable", "needs_review"}
    assert result["gates"]
    assert result["brief_summary"]["provider"] == "deterministic-contract-intelligence-v12"
    assert result["math_summary"]["provider"] == "canadian-contract-math-audit-v13"
    assert result["dependency_summary"]["provider"] == "optional-dependency-adapter-plan-v14"


def test_evaluate_normalized_packet_rejects_empty_pages():
    with pytest.raises(AdapterQualityHarnessError):
        evaluate_normalized_packet({"adapter": "marker", "ocr_pages": []})


def test_evaluate_adapter_payload_combines_preview_validation_and_evaluation():
    result = evaluate_adapter_payload(marker_payload())

    assert result["provider"] == "adapter-payload-evaluation-v15"
    assert result["adapter"] == "marker"
    assert result["preview"]["provider"] == "adapter-payload-preview-v15"
    assert result["validation"]["provider"] == "normalized-packet-validator-v15"
    assert result["evaluation"]["provider"] == "adapter-quality-harness-v15"
    assert result["ocr_pages"]
    assert result["quality"]["has_rate"] is True


def test_evaluate_adapter_payload_blocks_weak_payload_but_still_returns_actions():
    result = evaluate_adapter_payload(thin_payload())

    assert result["evaluation"]["score"]["level"] == "blocked"
    assert result["evaluation"]["next_actions"]
    assert result["validation"]["valid_for_contract_review"] is True


def test_evaluate_adapter_payload_rejects_unknown_shapes():
    with pytest.raises(Exception):
        evaluate_adapter_payload({"hello": "world"})
