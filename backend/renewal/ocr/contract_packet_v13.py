"""V13 lender and reviewer packet generation.

This is another no-dependency layer. It turns the contract brief, playbook,
math audit and research radar into a practical packet a reviewer can use before
calling or emailing a lender. It deliberately avoids raw OCR text and account
identifiers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contract_intelligence import create_contract_brief
from .contract_math_v13 import build_contract_math_audit_from_brief
from .contract_playbook import build_contract_playbook_from_brief
from .research_radar_v13 import build_research_radar_from_brief


class ContractPacketError(ValueError):
    """A lender packet could not be generated safely."""


@dataclass(frozen=True)
class PacketLine:
    id: str
    label: str
    text: str
    evidence: tuple[str, ...]
    action: str

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


def _field(brief: dict, key: str) -> dict:
    return brief.get("extraction", {}).get("fields", {}).get(key, {})


def _display(brief: dict, key: str) -> str | None:
    payload = _field(brief, key)
    if not payload:
        return None
    value = payload.get("display_value")
    if value is None:
        value = payload.get("value")
    if value is None:
        return None
    if key in {"balance", "payment_amount"}:
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if key in {"contract_rate", "posted_rate", "contract_discount", "offered_rate", "current_rate"}:
        text = str(value)
        return text if text.endswith("%") else f"{text}%"
    return str(value)


def _line_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def borrower_safe_snapshot(brief: dict) -> dict:
    fields = {}
    for key in (
        "balance",
        "contract_rate",
        "posted_rate",
        "contract_discount",
        "offered_rate",
        "term_months",
        "amortization_months",
        "mortgage_start_date",
        "maturity_date",
        "payment_amount",
        "frequency",
    ):
        value = _display(brief, key)
        if value is not None:
            fields[key] = {
                "display_value": value,
                "evidence": f"field:{key}",
                "confidence": _field(brief, key).get("confidence"),
            }
    return {
        "classification": brief.get("classification"),
        "readiness": brief.get("readiness"),
        "fields": fields,
        "raw_ocr_stored": False,
    }


def lender_question_packet(brief: dict, math_audit: dict) -> list[dict]:
    questions: list[PacketLine] = []
    for index, item in enumerate(brief.get("lender_questions", []), 1):
        questions.append(
            PacketLine(
                id=_line_id("lender-question", index),
                label=str(item.get("topic") or "lender question"),
                text=str(item.get("question") or "Please confirm this mortgage item."),
                evidence=tuple(item.get("evidence") or ()),
                action="ask_lender",
            )
        )
    offset = len(questions)
    for index, prompt in enumerate(math_audit.get("disclosure_prompts", []), 1):
        questions.append(
            PacketLine(
                id=_line_id("disclosure-question", offset + index),
                label=str(prompt.get("id") or "disclosure prompt"),
                text=str(prompt.get("question") or ""),
                evidence=tuple(prompt.get("evidence") or ()),
                action="confirm_before_relying",
            )
        )
    seen = set()
    deduped = []
    for item in questions:
        key = (item.text.lower(), item.action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item.public())
    return deduped


def evidence_appendix(brief: dict, math_audit: dict) -> dict:
    graph = brief.get("evidence_graph", {})
    nodes = graph.get("nodes", [])
    wanted = {
        "field:balance",
        "field:contract_rate",
        "field:posted_rate",
        "field:contract_discount",
        "field:offered_rate",
        "field:maturity_date",
        "field:mortgage_start_date",
        "clause:interest_rate_differential",
        "clause:three_month_interest_penalty",
        "calculation:contract_discount",
    }
    appendix_nodes = []
    for node in nodes:
        if node.get("id") not in wanted:
            continue
        appendix_nodes.append(
            {
                "id": node.get("id"),
                "kind": node.get("kind"),
                "label": node.get("label"),
                "value": node.get("value"),
                "confidence": node.get("confidence"),
                "page": node.get("page"),
                "excerpt": node.get("excerpt"),
            }
        )
    return {
        "node_count": len(appendix_nodes),
        "nodes": appendix_nodes,
        "formula_ids": [item["id"] for item in math_audit.get("formula_walkthroughs", [])],
        "penalty_scenario_ids": [item["id"] for item in math_audit.get("penalty_scenarios", [])],
    }


def reviewer_signoff_gates(playbook: dict, math_audit: dict, radar: dict) -> dict:
    gates = []
    manual = playbook.get("manual_review_gates", {})
    if manual.get("blocking_task_ids"):
        gates.append(
            {
                "id": "clear-blocking-tasks",
                "status": "blocked",
                "instruction": "Clear critical review tasks before finalizing the packet.",
                "references": manual.get("blocking_task_ids", []),
            }
        )
    else:
        gates.append(
            {
                "id": "clear-blocking-tasks",
                "status": "ready_for_review",
                "instruction": "No critical local playbook tasks are open, but human review is still required.",
                "references": [],
            }
        )
    missing = math_audit.get("confidence", {}).get("missing_required", [])
    gates.append(
        {
            "id": "required-fields",
            "status": "blocked" if missing else "ready_for_review",
            "instruction": "Confirm every required comparison field against the lender document.",
            "references": [f"field:{key}" for key in missing],
        }
    )
    gates.append(
        {
            "id": "lender-certified-payout",
            "status": "required",
            "instruction": "Obtain a written lender payout statement before using penalty or discharge numbers.",
            "references": ["ask-payout-statement"],
        }
    )
    gates.append(
        {
            "id": "no-dependency-policy",
            "status": "met" if not radar.get("dependency_policy", {}).get("new_pip_dependencies") else "review",
            "instruction": "Confirm this packet was generated by local code without new model downloads or GitHub imports.",
            "references": ["dependency_policy"],
        }
    )
    return {
        "can_send_to_lender": all(gate["status"] in {"ready_for_review", "required", "met"} for gate in gates),
        "gates": gates,
        "note": "Sending to a lender is a workflow action; it does not mean the contract review is complete.",
    }


def reviewer_summary(brief: dict, math_audit: dict, radar: dict) -> list[str]:
    summary = []
    readiness = brief.get("readiness", {})
    summary.append(f"Readiness state: {readiness.get('state', 'unknown')}.")
    risk_count = brief.get("risk_assessment", {}).get("risk_count", 0)
    summary.append(f"Detected review risks: {risk_count}.")
    confidence = math_audit.get("confidence", {}).get("level", "unknown")
    summary.append(f"Math audit confidence: {confidence}; lender certification is still required.")
    top_needs = [need["label"] for need in radar.get("adapter_needs", [])[:3]]
    if top_needs:
        summary.append("Top local adapter needs: " + "; ".join(top_needs) + ".")
    return summary


def build_lender_packet_from_brief(brief: dict) -> dict:
    if not isinstance(brief, dict) or brief.get("provider") != "deterministic-contract-intelligence-v12":
        raise ContractPacketError("Expected a V12 contract-intelligence brief")
    playbook = build_contract_playbook_from_brief(brief)
    math_audit = build_contract_math_audit_from_brief(brief)
    radar = build_research_radar_from_brief(brief)
    questions = lender_question_packet(brief, math_audit)
    appendix = evidence_appendix(brief, math_audit)
    signoff = reviewer_signoff_gates(playbook, math_audit, radar)
    return {
        "provider": "lender-review-packet-v13",
        "filename": brief.get("filename"),
        "snapshot": borrower_safe_snapshot(brief),
        "reviewer_summary": reviewer_summary(brief, math_audit, radar),
        "lender_questions": questions,
        "evidence_appendix": appendix,
        "signoff": signoff,
        "dependency_policy": radar.get("dependency_policy"),
        "source_providers": {
            "brief": brief.get("provider"),
            "playbook": playbook.get("provider"),
            "math_audit": math_audit.get("provider"),
            "research_radar": radar.get("provider"),
        },
        "notice": "This packet is for review and lender follow-up. It excludes raw OCR text and is not legal advice.",
    }


def create_lender_packet(pages: list[Any], *, filename: str = "ocr.txt",
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
    return build_lender_packet_from_brief(brief)
