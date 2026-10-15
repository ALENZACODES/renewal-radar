import pytest

from renewal.ocr.contract_intelligence import create_contract_brief
from renewal.ocr.contract_playbook import (
    ContractPlaybookError,
    PlaybookTask,
    build_contract_playbook_from_brief,
    checklist_from_tasks,
    comparison_prefill_status,
    create_contract_playbook,
    field_review_matrix,
    manual_review_gates,
    sort_tasks,
    timeline,
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
Interest rate differential applies if discharged early.
The penalty may be the greater of three months interest or the interest rate differential.
Prepayment privilege: 20% lump sum each year.
Offer expires: 2027-02-15.
"""


def pages(text=SAMPLE_TEXT, confidence=0.94):
    return [{"page_number": 1, "text": text, "mean_confidence": confidence}]


def brief(text=SAMPLE_TEXT, question="What should I ask the lender?"):
    return create_contract_brief(
        pages(text),
        filename="renewal-contract.txt",
        question=question,
    )


def by_id(tasks):
    return {task["id"]: task for task in tasks}


def test_playbook_turns_contract_brief_into_prioritized_review_workflow():
    playbook = build_contract_playbook_from_brief(brief())
    tasks = playbook["tasks"]
    owners = {task["owner"] for task in tasks}

    assert playbook["provider"] == "contract-review-playbook-v12"
    assert playbook["source_brief_provider"] == "deterministic-contract-intelligence-v12"
    assert playbook["checklist"]["task_count"] == len(tasks)
    assert playbook["checklist"]["open_task_count"] == len(tasks)
    assert playbook["checklist"]["by_priority"]["high"] >= 1
    assert {"broker_or_reviewer", "lender"} <= owners
    assert tasks[0]["priority"] in {"critical", "high"}
    assert all(isinstance(task["evidence"], list) for task in tasks)
    assert all(task["instructions"] for task in tasks)
    assert "ABCD-1234-5678" not in str(playbook)


def test_playbook_preserves_ird_discount_and_date_review_actions():
    playbook = build_contract_playbook_from_brief(brief())
    tasks = by_id(playbook["tasks"])
    joined_titles = " ".join(task["title"].lower() for task in tasks.values())

    assert "discharge" in joined_titles
    assert "discount" in joined_titles
    assert any("maturity date" in task["title"].lower() for task in tasks.values())
    assert any("clause:interest_rate_differential" in task["evidence"] for task in tasks.values())
    assert any("field:contract_discount" in task["evidence"] for task in tasks.values())
    assert any("field:mortgage_start_date" in task["evidence"] for task in tasks.values())


def test_missing_required_fields_create_critical_tasks_and_block_prefill():
    text = "Contract rate: 4.39%\nPosted rate: 5.69%\nContract discount: 1.30%"
    playbook = create_contract_playbook(pages(text), filename="thin-contract.txt")
    missing_tasks = [task for task in playbook["tasks"] if task["id"].startswith("missing-")]

    assert playbook["readiness"]["state"] == "blocked"
    assert "balance" in playbook["readiness"]["missing_required"]
    assert playbook["prefill"]["can_prefill"] is False
    assert playbook["manual_review_gates"]["can_mark_ready"] is False
    assert playbook["checklist"]["critical_task_count"] >= 1
    assert missing_tasks
    assert all(task["priority"] == "critical" for task in missing_tasks)
    assert all(task["due_hint"] == "before_comparison_prefill" for task in missing_tasks)


def test_complete_sample_can_prefill_comparison_only_with_human_approval_note():
    playbook = create_contract_playbook(pages(), filename="renewal-contract.txt")
    prefill = playbook["prefill"]

    assert prefill["can_prefill"] is True
    assert prefill["missing_required"] == []
    assert prefill["blocked_by_risk"] == []
    assert prefill["draft"]["balance"] == 480000.0
    assert "account_numbers" in prefill["excluded_fields"]
    assert "human approval" in prefill["note"]


def test_field_review_matrix_marks_required_low_confidence_and_risky_fields():
    low_confidence_brief = brief(
        SAMPLE_TEXT.replace("Contract discount: 1.30%", "Contract discount: 0.30%"),
    )
    matrix = field_review_matrix(low_confidence_brief)
    by_field = {row["field"]: row for row in matrix}

    assert by_field["balance"]["review_action"] == "required_for_prefill"
    assert by_field["contract_discount"]["review_action"] == "investigate_risk"
    assert by_field["contract_discount"]["linked_risk"] == "discount-math-review"
    assert all(row["evidence"].startswith("field:") for row in matrix)


def test_manual_review_gates_expose_blocking_tasks_and_lender_questions():
    playbook = build_contract_playbook_from_brief(brief())
    gates = playbook["manual_review_gates"]

    assert gates["can_mark_ready"] is True
    assert gates["blocking_task_ids"] == []
    assert gates["lender_task_ids"]
    assert any("Rate, discount, date" in item for item in gates["required_approvals"])
    assert "legal" in gates["note"]


def test_timeline_includes_maturity_date_and_review_milestones():
    generated = timeline(brief())
    names = [milestone["name"] for milestone in generated["milestones"]]
    maturity = next(item for item in generated["milestones"] if item["name"] == "maturity_date")

    assert generated["maturity_days"] is not None
    assert names[:3] == ["review_ocr_fields", "ask_lender_questions", "comparison_ready"]
    assert maturity["date"] == "2027-03-01"
    assert "lender deadlines" in maturity["detail"]


def test_question_answer_is_carried_into_playbook_when_requested():
    playbook = create_contract_playbook(
        pages(),
        filename="renewal-contract.txt",
        question="Explain the contract discount",
    )

    assert playbook["question_answer"]["topic"] == "posted_rate_discount"
    assert "calculation:contract_discount" in playbook["question_answer"]["evidence"]


def test_sorting_and_checklist_helpers_are_stable_for_ui_rendering():
    tasks = [
        PlaybookTask("task-low", "Low", "low", "broker_or_reviewer", "open", "this_week", (), ("Do it.",)),
        PlaybookTask("task-critical", "Critical", "critical", "lender", "open", "today", (), ("Do it.",)),
        PlaybookTask("task-high", "High", "high", "broker_or_reviewer", "open", "soon", (), ("Do it.",)),
    ]
    sorted_tasks = sort_tasks(tasks)
    checklist = checklist_from_tasks(sorted_tasks)

    assert [task.id for task in sorted_tasks] == ["task-critical", "task-high", "task-low"]
    assert checklist["task_count"] == 3
    assert checklist["critical_task_count"] == 1
    assert checklist["by_owner"]["broker_or_reviewer"] == 2


def test_comparison_prefill_blocks_high_risk_discount_mismatch():
    risky = brief(SAMPLE_TEXT.replace("Contract discount: 1.30%", "Contract discount: 0.30%"))
    prefill = comparison_prefill_status(risky)

    assert prefill["can_prefill"] is False
    assert "discount-math-review" in prefill["blocked_by_risk"]


def test_invalid_brief_is_rejected():
    with pytest.raises(ContractPlaybookError):
        build_contract_playbook_from_brief({"provider": "older-brief"})
