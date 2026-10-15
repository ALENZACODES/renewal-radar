import pytest

from renewal.ocr.contract_intelligence import (
    ContractIntelligenceError,
    answer_contract_question,
    assess_contract_risks,
    build_evidence_graph,
    create_contract_brief,
    lender_questions,
    match_question_profile,
    readiness_assessment,
)
from renewal.ocr.contract_sources import contract_source_map
from renewal.ocr.document_understanding import understand_ocr_document


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


def understanding(text=SAMPLE_TEXT):
    return understand_ocr_document(pages(text), filename="renewal.txt")


def node_ids(graph):
    return {node["id"] for node in graph["nodes"]}


def edge_pairs(graph):
    return {(edge["source"], edge["target"], edge["relation"]) for edge in graph["edges"]}


def test_evidence_graph_contains_fields_clauses_checks_and_calculations():
    result = understanding()
    graph = build_evidence_graph(result)
    ids = node_ids(graph)
    assert "field:contract_rate" in ids
    assert "field:posted_rate" in ids
    assert "field:contract_discount" in ids
    assert "field:mortgage_start_date" in ids
    assert "clause:interest_rate_differential" in ids
    assert "check:contract_rate_discount_math" in ids
    assert "calculation:contract_discount" in ids
    assert graph["summary"]["has_rate_context"] is True
    assert graph["summary"]["has_penalty_context"] is True
    assert graph["summary"]["has_timeline_context"] is True
    assert graph["summary"]["node_count"] >= 20
    assert "ABCD-1234-5678" not in str(graph)


def test_evidence_edges_link_rate_and_timeline_math():
    graph = build_evidence_graph(understanding())
    pairs = edge_pairs(graph)
    assert ("field:posted_rate", "calculation:contract_discount", "feeds_calculation") in pairs
    assert ("field:contract_rate", "check:contract_rate_discount_math", "checked_by") in pairs
    assert ("field:term_months", "calculation:term_timeline", "feeds_calculation") in pairs
    assert ("field:maturity_date", "clause:interest_rate_differential", "context_for") in pairs


def test_risk_assessment_flags_ird_and_three_month_interest():
    risks = assess_contract_risks(understanding())
    ids = {risk["id"] for risk in risks["risks"]}
    assert "ird-language-found" in ids
    assert "three-month-interest-language" in ids
    assert risks["risk_score"] > 0
    assert risks["risk_level"] in {"low", "medium", "high"}


def test_risk_assessment_flags_discount_mismatch():
    text = SAMPLE_TEXT.replace("Contract discount: 1.30%", "Contract discount: 0.30%")
    risks = assess_contract_risks(understanding(text))
    by_id = {risk["id"]: risk for risk in risks["risks"]}
    assert "discount-math-review" in by_id
    assert by_id["discount-math-review"]["severity"] == "high"
    assert "posted rate" in by_id["discount-math-review"]["actions"][0].lower()


def test_readiness_blocks_when_required_fields_missing():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%\nContract discount: 1.30%"
    understood = understanding(text)
    risks = assess_contract_risks(understood)
    readiness = readiness_assessment(understood, risks)
    assert readiness["state"] == "blocked"
    assert "balance" in readiness["missing_required"]
    assert readiness["can_finalize_without_human_review"] is False


def test_readiness_is_reviewable_when_core_fields_exist():
    understood = understanding()
    risks = assess_contract_risks(understood)
    readiness = readiness_assessment(understood, risks)
    assert readiness["state"] in {"ready_with_review", "review_required"}
    assert readiness["missing_required"] == []
    assert readiness["can_prefill_comparison"] is True


def test_lender_questions_are_prioritized_and_evidence_linked():
    understood = understanding()
    risks = assess_contract_risks(understood)
    questions = lender_questions(understood, risks)
    assert questions
    assert questions[0]["priority"] == "high"
    topics = {item["topic"] for item in questions}
    assert "interest_rate_differential" in topics
    assert "contract_discount" in topics
    assert all(isinstance(item["evidence"], list) for item in questions)


@pytest.mark.parametrize(
    "question,topic",
    [
        ("What is the contract rate?", "contract_rate"),
        ("How does posted rate discount work?", "posted_rate_discount"),
        ("Explain IRD penalty", "interest_rate_differential"),
        ("What is the term?", "term"),
        ("What is my amortization?", "amortization"),
        ("Does payment include tax?", "payment"),
        ("What date did the mortgage start?", "dates"),
        ("Can I prepay?", "prepayment"),
        ("What should I ask the lender?", "risks"),
    ],
)
def test_question_profile_matching(question, topic):
    assert match_question_profile(question).topic == topic


def test_answer_contract_rate_question_from_evidence():
    understood = understanding()
    answer = answer_contract_question(understood, "What is the contract rate?")
    assert answer["topic"] == "contract_rate"
    assert "Contract rate: 4.39%" in answer["answer"]
    assert "field:contract_rate" in answer["evidence"]
    assert answer["confidence"] in {"high", "medium"}


def test_answer_discount_question_includes_calculation():
    understood = understanding()
    answer = answer_contract_question(understood, "Explain posted rate and contract discount")
    assert answer["topic"] == "posted_rate_discount"
    assert "Contract discount" in answer["answer"]
    assert "Discount math" in answer["answer"]
    assert "calculation:contract_discount" in answer["evidence"]


def test_answer_ird_question_is_cautious():
    understood = understanding()
    answer = answer_contract_question(understood, "What is my IRD penalty?")
    assert answer["topic"] == "interest_rate_differential"
    assert "lender-specific" in answer["answer"]
    assert "written payout statement" in answer["answer"]
    assert "clause:interest_rate_differential" in answer["evidence"]


def test_answer_payment_question_includes_canadian_estimate():
    understood = understanding()
    answer = answer_contract_question(understood, "What should the payment be?")
    assert answer["topic"] == "payment"
    assert "Canadian fixed-rate estimate" in answer["answer"]
    assert "calculation:payment_estimate" in answer["evidence"]


def test_answer_unknown_question_falls_back_to_general_evidence():
    understood = understanding()
    answer = answer_contract_question(understood, "Tell me about this renewal")
    assert answer["topic"] == "general"
    assert answer["evidence"]
    assert any("OCR-derived answers require human verification" in item for item in answer["caveats"])


def test_empty_question_is_rejected():
    with pytest.raises(ContractIntelligenceError):
        answer_contract_question(understanding(), "   ")


def test_create_contract_brief_contains_graph_risks_questions_and_answer():
    brief = create_contract_brief(
        pages(),
        filename="renewal.txt",
        question="Explain the contract discount",
    )
    assert brief["provider"] == "deterministic-contract-intelligence-v12"
    assert brief["classification"]["type"] == "renewal_offer"
    assert brief["evidence_graph"]["summary"]["node_count"] >= 20
    assert brief["risk_assessment"]["risk_count"] >= 1
    assert brief["lender_questions"]
    assert brief["answer"]["topic"] == "posted_rate_discount"
    assert brief["raw_ocr_stored"] is False
    assert "ABCD-1234-5678" not in str(brief)


def test_contract_source_map_documents_public_references():
    sources = contract_source_map()
    keys = {item["key"] for item in sources["sources"]}
    assert {"docling", "unstructured", "presidio", "cuad", "legal_bert", "layoutparser"} <= keys
    by_key = {item["key"]: item for item in sources["sources"]}
    assert "October 10, 2026" in by_key["unstructured"]["latest_signal"]
    assert "510 expert-labeled contracts" in by_key["cuad"]["latest_signal"]
    assert "not bundled" in by_key["legal_bert"]["not_used_for"]
    assert sources["verified_date"] == "2026-10-13"
