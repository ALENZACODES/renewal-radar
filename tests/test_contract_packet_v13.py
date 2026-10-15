import pytest

from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.contract_math_v13 import build_contract_math_audit_from_brief
from renewal.ocr.contract_packet_v13 import (
    ContractPacketError,
    borrower_safe_snapshot,
    build_lender_packet_from_brief,
    evidence_appendix,
    lender_question_packet,
    reviewer_signoff_gates,
)
from renewal.ocr.contract_playbook import build_contract_playbook_from_brief
from renewal.ocr.research_radar_v13 import build_research_radar_from_brief


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
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def pages(text=SAMPLE_TEXT):
    return [{"page_number": 1, "text": text, "mean_confidence": 0.94}]


def brief(text=SAMPLE_TEXT):
    return create_contract_brief(
        pages(text),
        filename="renewal-contract.txt",
        question="What should I ask the lender?",
    )


def test_borrower_safe_snapshot_includes_review_fields_but_not_raw_identifiers():
    snapshot = borrower_safe_snapshot(brief())

    assert snapshot["raw_ocr_stored"] is False
    assert snapshot["fields"]["balance"]["display_value"] == "$480,000.00"
    assert snapshot["fields"]["contract_discount"]["evidence"] == "field:contract_discount"
    assert "mortgage_reference" not in snapshot["fields"]
    assert "ABCD-1234-5678" not in str(snapshot)


def test_lender_question_packet_combines_lender_questions_and_disclosure_prompts():
    contract = brief()
    math_audit = build_contract_math_audit_from_brief(contract)
    questions = lender_question_packet(contract, math_audit)
    texts = " ".join(item["text"] for item in questions)

    assert questions
    assert any(item["action"] == "ask_lender" for item in questions)
    assert any(item["action"] == "confirm_before_relying" for item in questions)
    assert "written payout statement" in texts
    assert len({(item["text"], item["action"]) for item in questions}) == len(questions)


def test_evidence_appendix_keeps_key_nodes_and_formula_ids():
    contract = brief()
    appendix = evidence_appendix(contract, build_contract_math_audit_from_brief(contract))
    node_ids = {node["id"] for node in appendix["nodes"]}

    assert "field:contract_rate" in node_ids
    assert "field:maturity_date" in node_ids
    assert "clause:interest_rate_differential" in node_ids
    assert "formula-contract-discount" in appendix["formula_ids"]
    assert "three-month-interest" in appendix["penalty_scenario_ids"]
    assert "ABCD-1234-5678" not in str(appendix)


def test_reviewer_signoff_gates_require_lender_certified_payout():
    contract = brief()
    playbook = build_contract_playbook_from_brief(contract)
    math_audit = build_contract_math_audit_from_brief(contract)
    radar = build_research_radar_from_brief(contract)
    signoff = reviewer_signoff_gates(playbook, math_audit, radar)
    gate_ids = {gate["id"] for gate in signoff["gates"]}

    assert signoff["can_send_to_lender"] is True
    assert "lender-certified-payout" in gate_ids
    assert "no-dependency-policy" in gate_ids
    assert any(gate["status"] == "required" for gate in signoff["gates"])


def test_reviewer_signoff_blocks_when_required_fields_are_missing():
    contract = brief("Contract rate: 4.39%\nPosted rate: 5.69%")
    playbook = build_contract_playbook_from_brief(contract)
    math_audit = build_contract_math_audit_from_brief(contract)
    radar = build_research_radar_from_brief(contract)
    signoff = reviewer_signoff_gates(playbook, math_audit, radar)

    assert signoff["can_send_to_lender"] is False
    assert any(gate["id"] == "required-fields" and gate["status"] == "blocked" for gate in signoff["gates"])
    assert any("field:balance" in gate["references"] for gate in signoff["gates"])


def test_build_lender_packet_from_brief_returns_complete_packet():
    packet = build_lender_packet_from_brief(brief())

    assert packet["provider"] == "lender-review-packet-v13"
    assert packet["source_providers"]["math_audit"] == "canadian-contract-math-audit-v13"
    assert packet["source_providers"]["research_radar"] == "no-dependency-contract-research-radar-v13"
    assert packet["dependency_policy"]["new_pip_dependencies"] == []
    assert packet["snapshot"]["fields"]["offered_rate"]["display_value"] == "5.49%"
    assert packet["lender_questions"]
    assert packet["evidence_appendix"]["node_count"] >= 5
    assert packet["signoff"]["can_send_to_lender"] is True
    assert "ABCD-1234-5678" not in str(packet)


def test_lender_packet_for_thin_documents_preserves_blockers():
    packet = build_lender_packet_from_brief(brief("Contract rate: 4.39%\nPosted rate: 5.69%"))

    assert packet["snapshot"]["readiness"]["state"] == "blocked"
    assert packet["signoff"]["can_send_to_lender"] is False
    assert any("Readiness state: blocked" in item for item in packet["reviewer_summary"])
    assert any(question["id"].startswith("disclosure-question") for question in packet["lender_questions"])


def test_lender_packet_rejects_non_v12_briefs():
    with pytest.raises(ContractPacketError):
        build_lender_packet_from_brief({"provider": "old"})
