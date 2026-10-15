"""V15 multi-adapter comparison workbench.

This module compares several normalized/evaluated adapter payloads and chooses
the best candidate to feed the mortgage contract pipeline. It is useful when a
PDF has been run through more than one optional OCR/document engine.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .adapter_output_normalizer_v15 import AdapterNormalizationError
from .adapter_quality_harness_v15 import AdapterQualityHarnessError, evaluate_adapter_payload


class AdapterWorkbenchError(ValueError):
    """Adapter workbench input was not usable."""


@dataclass(frozen=True)
class CandidateScore:
    id: str
    adapter: str
    score: int
    level: str
    span_count: int
    table_count: int
    gate_failures: int
    gate_reviews: int
    has_money: bool
    has_rate: bool
    has_date: bool
    has_penalty_language: bool
    selected: bool
    reasons: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def _candidate_id(index: int, adapter: str) -> str:
    return f"candidate-{index:03d}-{adapter}"


def _quality_bonus(quality: dict) -> tuple[int, list[str]]:
    bonus = 0
    reasons: list[str] = []
    if quality.get("has_money"):
        bonus += 5
        reasons.append("money amount detected")
    if quality.get("has_rate"):
        bonus += 5
        reasons.append("interest rate detected")
    if quality.get("has_date"):
        bonus += 4
        reasons.append("date detected")
    if quality.get("has_penalty_language"):
        bonus += 4
        reasons.append("penalty language detected")
    if quality.get("has_tables"):
        bonus += 3
        reasons.append("table evidence available")
    if quality.get("low_confidence_span_ids"):
        penalty = min(12, len(quality["low_confidence_span_ids"]) * 2)
        bonus -= penalty
        reasons.append(f"{len(quality['low_confidence_span_ids'])} low-confidence spans")
    return bonus, reasons


def score_evaluation(index: int, evaluation_packet: dict) -> CandidateScore:
    adapter = str(evaluation_packet.get("adapter") or "unknown")
    evaluation = evaluation_packet.get("evaluation", {})
    score_payload = evaluation.get("score", {})
    quality = evaluation_packet.get("quality", {})
    summary = evaluation_packet.get("preview", {}).get("summary", {})
    base_score = int(score_payload.get("score") or 0)
    bonus, reasons = _quality_bonus(quality)
    gate_failures = int(score_payload.get("fail_count") or 0)
    gate_reviews = int(score_payload.get("review_count") or 0)
    if gate_failures:
        reasons.append(f"{gate_failures} blocking quality gates")
    if gate_reviews:
        reasons.append(f"{gate_reviews} review gates")
    final_score = max(0, min(100, base_score + bonus))
    return CandidateScore(
        id=_candidate_id(index, adapter),
        adapter=adapter,
        score=final_score,
        level=str(score_payload.get("level") or "unknown"),
        span_count=int(summary.get("span_count") or 0),
        table_count=int(summary.get("table_count") or 0),
        gate_failures=gate_failures,
        gate_reviews=gate_reviews,
        has_money=bool(quality.get("has_money")),
        has_rate=bool(quality.get("has_rate")),
        has_date=bool(quality.get("has_date")),
        has_penalty_language=bool(quality.get("has_penalty_language")),
        selected=False,
        reasons=tuple(reasons),
    )


def rank_candidate_scores(scores: list[CandidateScore]) -> list[CandidateScore]:
    ranked = sorted(
        scores,
        key=lambda item: (
            -item.score,
            item.gate_failures,
            item.gate_reviews,
            -item.table_count,
            -item.span_count,
            item.adapter,
        ),
    )
    if not ranked:
        return []
    selected_id = ranked[0].id
    return [
        CandidateScore(
            id=item.id,
            adapter=item.adapter,
            score=item.score,
            level=item.level,
            span_count=item.span_count,
            table_count=item.table_count,
            gate_failures=item.gate_failures,
            gate_reviews=item.gate_reviews,
            has_money=item.has_money,
            has_rate=item.has_rate,
            has_date=item.has_date,
            has_penalty_language=item.has_penalty_language,
            selected=item.id == selected_id,
            reasons=item.reasons,
        )
        for item in ranked
    ]


def compare_adapter_payloads(candidates: list[dict[str, Any]]) -> dict:
    if not candidates:
        raise AdapterWorkbenchError("At least one adapter candidate is required")
    evaluations = []
    errors = []
    scores: list[CandidateScore] = []
    for index, candidate in enumerate(candidates, 1):
        adapter = candidate.get("adapter")
        payload = candidate.get("payload")
        candidate_id = _candidate_id(index, str(adapter or "auto"))
        try:
            evaluation = evaluate_adapter_payload(payload, adapter)
        except (AdapterNormalizationError, AdapterQualityHarnessError, Exception) as exc:
            errors.append(
                {
                    "id": candidate_id,
                    "adapter": adapter or "auto",
                    "message": str(exc),
                    "status": "failed",
                }
            )
            continue
        evaluations.append({"id": candidate_id, **evaluation})
        scores.append(score_evaluation(index, evaluation))
    ranked = rank_candidate_scores(scores)
    selected = next((item for item in ranked if item.selected), None)
    selected_evaluation = None
    if selected:
        selected_evaluation = next((item for item in evaluations if item["id"] == selected.id), None)
    return {
        "provider": "adapter-comparison-workbench-v15",
        "candidate_count": len(candidates),
        "evaluated_count": len(evaluations),
        "error_count": len(errors),
        "scores": [item.public() for item in ranked],
        "selected_candidate_id": selected.id if selected else None,
        "selected_adapter": selected.adapter if selected else None,
        "selected_ocr_pages": selected_evaluation.get("ocr_pages", []) if selected_evaluation else [],
        "selected_quality": selected_evaluation.get("quality", {}) if selected_evaluation else {},
        "selected_next_actions": (
            selected_evaluation.get("evaluation", {}).get("next_actions", [])
            if selected_evaluation
            else []
        ),
        "errors": errors,
        "notice": "Use the selected candidate as the best local review input; still verify against the source document.",
    }


def consensus_signals(workbench: dict) -> dict:
    scores = workbench.get("scores", [])
    if not scores:
        return {
            "provider": "adapter-consensus-v15",
            "consensus": "none",
            "reason": "No adapter candidate was evaluated successfully.",
        }
    top = scores[0]
    second = scores[1] if len(scores) > 1 else None
    gap = top["score"] - second["score"] if second else top["score"]
    if top["gate_failures"]:
        consensus = "blocked"
        reason = "Top candidate still has blocking gates."
    elif gap >= 15:
        consensus = "strong"
        reason = "Top candidate is clearly ahead of the next candidate."
    elif gap >= 5:
        consensus = "moderate"
        reason = "Top candidate is ahead but another candidate is close."
    else:
        consensus = "weak"
        reason = "Candidates are close; reviewer should compare evidence before choosing."
    shared_features = {
        "money": sum(1 for item in scores if item.get("has_money")),
        "rate": sum(1 for item in scores if item.get("has_rate")),
        "date": sum(1 for item in scores if item.get("has_date")),
        "penalty_language": sum(1 for item in scores if item.get("has_penalty_language")),
    }
    return {
        "provider": "adapter-consensus-v15",
        "consensus": consensus,
        "reason": reason,
        "score_gap": gap,
        "top_candidate_id": top.get("id"),
        "top_adapter": top.get("adapter"),
        "shared_features": shared_features,
        "candidate_count": len(scores),
    }


def merge_candidate_pages(workbench: dict, *, max_pages: int = 16) -> list[dict]:
    selected = workbench.get("selected_ocr_pages") or []
    if selected:
        return selected[:max_pages]
    return []


def build_workbench_report(candidates: list[dict[str, Any]]) -> dict:
    workbench = compare_adapter_payloads(candidates)
    consensus = consensus_signals(workbench)
    return {
        "provider": "adapter-workbench-report-v15",
        "workbench": workbench,
        "consensus": consensus,
        "merged_pages": merge_candidate_pages(workbench),
        "ready_for_contract_pipeline": bool(workbench.get("selected_ocr_pages"))
        and consensus.get("consensus") != "blocked",
    }
