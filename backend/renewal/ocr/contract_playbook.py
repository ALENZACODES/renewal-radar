"""V12 action playbooks for mortgage contract review.

The contract-intelligence brief explains what was found. The playbook turns that
brief into a practical review workflow: what to verify first, which lender
questions to ask, which values are ready for a comparison form, and which items
block finalization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from .contract_intelligence import create_contract_brief


class ContractPlaybookError(ValueError):
    """A playbook cannot be generated from the supplied contract brief."""


@dataclass(frozen=True)
class PlaybookTask:
    id: str
    title: str
    priority: str
    owner: str
    status: str
    due_hint: str
    evidence: tuple[str, ...]
    instructions: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        data["instructions"] = list(self.instructions)
        return data


PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PREFILL_REQUIRED_FIELDS = ("balance", "offered_rate", "amortization_months", "maturity_date")


def _task_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def _priority_from_risk(severity: str) -> str:
    if severity == "high":
        return "critical"
    if severity == "medium":
        return "high"
    return "medium"


def _due_hint(priority: str, maturity_days: int | None) -> str:
    if maturity_days is not None and maturity_days <= 0:
        return "today"
    if priority == "critical":
        return "within_1_business_day"
    if priority == "high":
        return "within_2_business_days"
    if maturity_days is not None and maturity_days <= 14:
        return "before_maturity_deadline"
    return "this_week"


def _maturity_days(brief: dict) -> int | None:
    value = (
        brief.get("extraction", {})
        .get("fields", {})
        .get("maturity_date", {})
        .get("value")
    )
    if not value:
        return None
    try:
        return (date.fromisoformat(str(value)) - date.today()).days
    except ValueError:
        return None


def risk_tasks(brief: dict) -> list[PlaybookTask]:
    maturity_days = _maturity_days(brief)
    tasks = []
    for index, risk in enumerate(brief.get("risk_assessment", {}).get("risks", []), 1):
        priority = _priority_from_risk(risk.get("severity", "low"))
        instructions = tuple(risk.get("actions") or ("Verify this item against the source document.",))
        tasks.append(
            PlaybookTask(
                id=_task_id("risk", index),
                title=str(risk.get("title") or "Review contract risk"),
                priority=priority,
                owner="broker_or_reviewer",
                status="open",
                due_hint=_due_hint(priority, maturity_days),
                evidence=tuple(risk.get("evidence") or ()),
                instructions=instructions,
            )
        )
    return tasks


def lender_question_tasks(brief: dict) -> list[PlaybookTask]:
    maturity_days = _maturity_days(brief)
    tasks = []
    for index, item in enumerate(brief.get("lender_questions", []), 1):
        priority = "high" if item.get("priority") == "high" else "medium"
        tasks.append(
            PlaybookTask(
                id=_task_id("lender", index),
                title=str(item.get("question") or "Ask lender a follow-up question"),
                priority=priority,
                owner="lender",
                status="open",
                due_hint=_due_hint(priority, maturity_days),
                evidence=tuple(item.get("evidence") or ()),
                instructions=(
                    "Ask the lender in writing.",
                    "Attach or quote the exact document line when possible.",
                    "Record the lender's answer before relying on the field.",
                ),
            )
        )
    return tasks


def missing_field_tasks(brief: dict) -> list[PlaybookTask]:
    missing = brief.get("readiness", {}).get("missing_required", [])
    tasks = []
    for index, field in enumerate(missing, 1):
        tasks.append(
            PlaybookTask(
                id=_task_id("missing", index),
                title=f"Collect required field: {str(field).replace('_', ' ')}",
                priority="critical",
                owner="broker_or_reviewer",
                status="open",
                due_hint="before_comparison_prefill",
                evidence=(f"field:{field}",),
                instructions=(
                    "Find the value in the original lender document.",
                    "If OCR missed it, enter a manual correction.",
                    "Do not finalize the review until this value is verified.",
                ),
            )
        )
    return tasks


def verification_tasks(brief: dict) -> list[PlaybookTask]:
    fields = brief.get("extraction", {}).get("fields", {})
    tasks = []
    verifiable = [
        ("balance", "Verify outstanding balance and balance date"),
        ("offered_rate", "Verify renewal offered rate"),
        ("contract_rate", "Verify contract rate label"),
        ("posted_rate", "Verify posted/comparison rate source"),
        ("contract_discount", "Verify contract discount"),
        ("term_months", "Verify term length"),
        ("amortization_months", "Verify remaining amortization"),
        ("maturity_date", "Verify maturity date"),
        ("mortgage_start_date", "Verify mortgage start/funding date"),
        ("payment_amount", "Verify payment amount and included components"),
        ("frequency", "Verify payment frequency"),
    ]
    for index, (field, title) in enumerate(verifiable, 1):
        if field not in fields:
            continue
        tasks.append(
            PlaybookTask(
                id=_task_id("verify", index),
                title=title,
                priority="medium",
                owner="broker_or_reviewer",
                status="open",
                due_hint="before_final_review",
                evidence=(f"field:{field}",),
                instructions=(
                    "Compare extracted value with the source document.",
                    "Confirm label context, not just the number.",
                    "Approve the field only after the source document matches.",
                ),
            )
        )
    return tasks


def sort_tasks(tasks: list[PlaybookTask]) -> list[PlaybookTask]:
    return sorted(tasks, key=lambda item: (PRIORITY_RANK.get(item.priority, 9), item.id))


def checklist_from_tasks(tasks: list[PlaybookTask]) -> dict:
    by_priority: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    for task in tasks:
        by_priority[task.priority] = by_priority.get(task.priority, 0) + 1
        by_owner[task.owner] = by_owner.get(task.owner, 0) + 1
    return {
        "task_count": len(tasks),
        "by_priority": by_priority,
        "by_owner": by_owner,
        "open_task_count": sum(1 for task in tasks if task.status == "open"),
        "critical_task_count": by_priority.get("critical", 0),
    }


def comparison_prefill_status(brief: dict) -> dict:
    fields = brief.get("extraction", {}).get("fields", {})
    draft = brief.get("extraction", {}).get("mortgage_draft", {})
    missing = [key for key in PREFILL_REQUIRED_FIELDS if key not in fields]
    blocked_by_risk = [
        risk["id"]
        for risk in brief.get("risk_assessment", {}).get("risks", [])
        if risk.get("severity") == "high"
    ]
    return {
        "can_prefill": not missing and not blocked_by_risk,
        "draft": draft,
        "missing_required": missing,
        "blocked_by_risk": blocked_by_risk,
        "excluded_fields": [
            "mortgage_reference",
            "raw_ocr_text",
            "account_numbers",
            "unverified_penalty_amounts",
        ],
        "note": "Prefill status still requires human approval before use.",
    }


def field_review_matrix(brief: dict) -> list[dict]:
    fields = brief.get("extraction", {}).get("fields", {})
    risks = brief.get("risk_assessment", {}).get("risks", [])
    risk_evidence = {
        evidence: risk.get("id")
        for risk in risks
        for evidence in risk.get("evidence", [])
        if isinstance(evidence, str) and evidence.startswith("field:")
    }
    rows = []
    for key, payload in sorted(fields.items()):
        evidence_id = f"field:{key}"
        confidence = str(payload.get("confidence") or "unknown")
        review_action = "verify"
        if key in PREFILL_REQUIRED_FIELDS:
            review_action = "required_for_prefill"
        if confidence == "low":
            review_action = "manual_rekey"
        if evidence_id in risk_evidence:
            review_action = "investigate_risk"
        rows.append(
            {
                "field": key,
                "display_value": payload.get("display_value") or payload.get("value"),
                "confidence": confidence,
                "evidence": evidence_id,
                "linked_risk": risk_evidence.get(evidence_id),
                "review_action": review_action,
            }
        )
    return rows


def manual_review_gates(brief: dict, tasks: list[PlaybookTask]) -> dict:
    critical_task_ids = [task.id for task in tasks if task.priority == "critical"]
    high_risk_ids = [
        risk.get("id")
        for risk in brief.get("risk_assessment", {}).get("risks", [])
        if risk.get("severity") == "high"
    ]
    lender_task_ids = [task.id for task in tasks if task.owner == "lender"]
    missing_required = brief.get("readiness", {}).get("missing_required", [])
    return {
        "can_mark_ready": not critical_task_ids and not high_risk_ids and not missing_required,
        "blocking_task_ids": critical_task_ids,
        "high_risk_ids": high_risk_ids,
        "lender_task_ids": lender_task_ids,
        "required_approvals": [
            "Every required field has been checked against the lender document.",
            "Every lender answer has been recorded before relying on it.",
            "Rate, discount, date, term and payment math have been reviewed by a human.",
            "No raw account or mortgage number is copied into downstream notes.",
        ],
        "note": "These gates control workflow readiness only; they do not replace legal or lender confirmation.",
    }


def timeline(brief: dict) -> dict:
    maturity_days = _maturity_days(brief)
    today = date.today()
    milestones = [
        {
            "name": "review_ocr_fields",
            "date": today.isoformat(),
            "detail": "Verify extracted values against the source document.",
        },
        {
            "name": "ask_lender_questions",
            "date": (today + timedelta(days=2)).isoformat(),
            "detail": "Send lender questions about IRD, discount, payment components and dates.",
        },
        {
            "name": "comparison_ready",
            "date": (today + timedelta(days=4)).isoformat(),
            "detail": "Use only verified fields for mortgage comparison.",
        },
    ]
    if maturity_days is not None:
        maturity = today + timedelta(days=maturity_days)
        milestones.append(
            {
                "name": "maturity_date",
                "date": maturity.isoformat(),
                "detail": "Extracted maturity date; confirm lender deadlines before this date.",
            }
        )
    return {
        "generated_at": today.isoformat(),
        "maturity_days": maturity_days,
        "milestones": milestones,
    }


def build_contract_playbook_from_brief(brief: dict) -> dict:
    if not isinstance(brief, dict) or brief.get("provider") != "deterministic-contract-intelligence-v12":
        raise ContractPlaybookError("Expected a V12 contract-intelligence brief")
    tasks = sort_tasks(
        missing_field_tasks(brief)
        + risk_tasks(brief)
        + lender_question_tasks(brief)
        + verification_tasks(brief)
    )
    return {
        "provider": "contract-review-playbook-v12",
        "filename": brief.get("filename"),
        "readiness": brief.get("readiness"),
        "checklist": checklist_from_tasks(tasks),
        "tasks": [task.public() for task in tasks],
        "prefill": comparison_prefill_status(brief),
        "field_review_matrix": field_review_matrix(brief),
        "manual_review_gates": manual_review_gates(brief, tasks),
        "timeline": timeline(brief),
        "question_answer": brief.get("answer"),
        "source_brief_provider": brief.get("provider"),
        "notice": "The playbook is an operational checklist; it is not legal advice.",
    }


def create_contract_playbook(pages: list[Any], *, filename: str = "ocr.txt",
                             corrections: dict[str, Any] | None = None,
                             min_confidence: float = 0.0,
                             question: str | None = None) -> dict:
    brief = create_contract_brief(
        pages,
        filename=filename,
        corrections=corrections,
        min_confidence=min_confidence,
        question=question,
    )
    return build_contract_playbook_from_brief(brief)
