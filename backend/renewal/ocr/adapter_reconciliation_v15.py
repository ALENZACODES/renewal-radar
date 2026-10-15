"""V15 field reconciliation across multiple adapter candidates."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .adapter_workbench_v15 import compare_adapter_payloads
from .contract_intelligence import create_contract_brief


class AdapterReconciliationError(ValueError):
    """Adapter reconciliation input was not usable."""


@dataclass(frozen=True)
class FieldVote:
    field: str
    value: Any
    display_value: str
    candidate_id: str
    adapter: str
    confidence: str
    evidence: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


@dataclass(frozen=True)
class ReconciledField:
    field: str
    selected_value: Any
    selected_display_value: str
    status: str
    confidence: str
    vote_count: int
    distinct_value_count: int
    candidate_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    note: str

    def public(self) -> dict:
        data = asdict(self)
        data["candidate_ids"] = list(self.candidate_ids)
        data["evidence"] = list(self.evidence)
        return data


CORE_FIELDS = (
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
)


def _canonical_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if field.endswith("_rate") or field == "contract_discount":
        match = re.search(r"\d+(?:\.\d+)?", text)
        return f"{float(match.group(0)):.4f}" if match else text
    if field in {"balance", "payment_amount"}:
        numeric = re.sub(r"[^0-9.]", "", text)
        return f"{float(numeric):.2f}" if numeric else text
    if field.endswith("_months"):
        match = re.search(r"\d+", text)
        return str(int(match.group(0))) if match else text
    return text


def _confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1, "unknown": 0}.get(str(value), 0)


def extract_votes_from_workbench(workbench: dict) -> list[FieldVote]:
    votes: list[FieldVote] = []
    for score in workbench.get("scores", []):
        candidate_id = score.get("id")
        pages = workbench.get("selected_ocr_pages", []) if score.get("selected") else []
        if not pages:
            # Re-evaluated payload details are intentionally not retained in the
            # compact workbench response; selected pages are the safe default.
            continue
        try:
            brief = create_contract_brief(pages, filename=f"{candidate_id}.txt")
        except Exception:
            continue
        fields = brief.get("extraction", {}).get("fields", {})
        for field in CORE_FIELDS:
            payload = fields.get(field)
            if not payload:
                continue
            votes.append(
                FieldVote(
                    field=field,
                    value=payload.get("value"),
                    display_value=str(payload.get("display_value") or payload.get("value")),
                    candidate_id=str(candidate_id),
                    adapter=str(score.get("adapter")),
                    confidence=str(payload.get("confidence") or "unknown"),
                    evidence=(f"field:{field}",),
                )
            )
    return votes


def extract_votes_from_candidates(candidates: list[dict[str, Any]]) -> tuple[dict, list[FieldVote]]:
    workbench = compare_adapter_payloads(candidates)
    votes: list[FieldVote] = []
    for score in workbench.get("scores", []):
        candidate_id = score.get("id")
        if not candidate_id:
            continue
        candidate_pages = []
        if score.get("selected"):
            candidate_pages = workbench.get("selected_ocr_pages", [])
        else:
            # Evaluate non-selected candidates again via the original payloads so
            # reconciliation can compare values rather than only scores.
            index = int(str(candidate_id).split("-")[1]) - 1
            if index < 0 or index >= len(candidates):
                continue
            try:
                candidate_workbench = compare_adapter_payloads([candidates[index]])
            except Exception:
                continue
            candidate_pages = candidate_workbench.get("selected_ocr_pages", [])
        if not candidate_pages:
            continue
        try:
            brief = create_contract_brief(candidate_pages, filename=f"{candidate_id}.txt")
        except Exception:
            continue
        for field, payload in brief.get("extraction", {}).get("fields", {}).items():
            if field not in CORE_FIELDS:
                continue
            votes.append(
                FieldVote(
                    field=field,
                    value=payload.get("value"),
                    display_value=str(payload.get("display_value") or payload.get("value")),
                    candidate_id=str(candidate_id),
                    adapter=str(score.get("adapter")),
                    confidence=str(payload.get("confidence") or "unknown"),
                    evidence=(f"field:{field}",),
                )
            )
    return workbench, votes


def reconcile_field(field: str, votes: list[FieldVote]) -> ReconciledField:
    if not votes:
        return ReconciledField(
            field=field,
            selected_value=None,
            selected_display_value="",
            status="missing",
            confidence="low",
            vote_count=0,
            distinct_value_count=0,
            candidate_ids=(),
            evidence=(),
            note="No adapter candidate extracted this field.",
        )
    buckets: dict[str, list[FieldVote]] = {}
    for vote in votes:
        buckets.setdefault(_canonical_value(field, vote.value), []).append(vote)
    ranked = sorted(
        buckets.items(),
        key=lambda item: (
            -len(item[1]),
            -max(_confidence_rank(vote.confidence) for vote in item[1]),
            item[0],
        ),
    )
    selected_votes = ranked[0][1]
    selected = sorted(selected_votes, key=lambda vote: -_confidence_rank(vote.confidence))[0]
    distinct_count = len(buckets)
    if distinct_count == 1 and len(selected_votes) >= 2:
        status = "consensus"
        confidence = "high"
        note = "Multiple adapter candidates agreed on this field."
    elif distinct_count == 1:
        status = "single_source"
        confidence = selected.confidence if selected.confidence in {"high", "medium"} else "medium"
        note = "Only one adapter candidate produced this field."
    else:
        status = "conflict"
        confidence = "medium" if len(selected_votes) > 1 else "low"
        note = "Adapter candidates disagreed; reviewer should inspect source evidence."
    return ReconciledField(
        field=field,
        selected_value=selected.value,
        selected_display_value=selected.display_value,
        status=status,
        confidence=confidence,
        vote_count=len(votes),
        distinct_value_count=distinct_count,
        candidate_ids=tuple(sorted({vote.candidate_id for vote in votes})),
        evidence=tuple(sorted({evidence for vote in votes for evidence in vote.evidence})),
        note=note,
    )


def reconcile_votes(votes: list[FieldVote]) -> dict:
    by_field: dict[str, list[FieldVote]] = {field: [] for field in CORE_FIELDS}
    for vote in votes:
        if vote.field in by_field:
            by_field[vote.field].append(vote)
    fields = [reconcile_field(field, field_votes).public() for field, field_votes in by_field.items()]
    conflicts = [field for field in fields if field["status"] == "conflict"]
    missing = [field for field in fields if field["status"] == "missing"]
    consensus = [field for field in fields if field["status"] == "consensus"]
    return {
        "provider": "adapter-field-reconciliation-v15",
        "fields": fields,
        "summary": {
            "field_count": len(fields),
            "consensus_count": len(consensus),
            "conflict_count": len(conflicts),
            "missing_count": len(missing),
            "vote_count": len(votes),
        },
        "review_required": bool(conflicts or missing),
    }


def reviewer_decisions_from_reconciliation(reconciliation: dict) -> list[dict]:
    decisions = []
    for field in reconciliation.get("fields", []):
        status = field.get("status")
        if status == "consensus":
            action = "verify_consensus"
            priority = "medium"
        elif status == "single_source":
            action = "verify_single_source"
            priority = "medium"
        elif status == "conflict":
            action = "resolve_conflict"
            priority = "high"
        else:
            action = "collect_missing"
            priority = "critical"
        decisions.append(
            {
                "field": field.get("field"),
                "action": action,
                "priority": priority,
                "selected_display_value": field.get("selected_display_value"),
                "note": field.get("note"),
                "evidence": field.get("evidence", []),
            }
        )
    return decisions


def build_reconciliation_report(candidates: list[dict[str, Any]]) -> dict:
    if not candidates:
        raise AdapterReconciliationError("At least one adapter candidate is required")
    workbench, votes = extract_votes_from_candidates(candidates)
    reconciliation = reconcile_votes(votes)
    return {
        "provider": "adapter-reconciliation-report-v15",
        "workbench": workbench,
        "reconciliation": reconciliation,
        "reviewer_decisions": reviewer_decisions_from_reconciliation(reconciliation),
        "ready_without_review": reconciliation["review_required"] is False,
        "notice": "Reconciled fields still require human verification against the source document.",
    }
