"""V15 quality harness for normalized adapter outputs.

The normalizer turns external adapter-shaped payloads into Renewal Radar pages.
This harness runs the normalized pages through the existing mortgage
understanding, math audit, lender packet and dependency-plan stack, then returns
a single review scorecard.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .adapter_output_normalizer_v15 import (
    AdapterNormalizationError,
    normalize_adapter_payload,
    preview_adapter_payload,
    validate_normalized_packet,
)
from .contract_intelligence import create_contract_brief
from .contract_math_v13 import build_contract_math_audit_from_brief
from .contract_packet_v13 import build_lender_packet_from_brief
from .dependency_adapters_v14 import build_dependency_adapter_plan_from_brief


class AdapterQualityHarnessError(ValueError):
    """Adapter quality harness could not evaluate the payload."""


@dataclass(frozen=True)
class QualityGate:
    id: str
    title: str
    status: str
    severity: str
    detail: str
    evidence: tuple[str, ...] = ()

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


REQUIRED_FIELD_KEYS = (
    "balance",
    "offered_rate",
    "amortization_months",
    "maturity_date",
)


def _gate(id_: str, title: str, status: str, severity: str,
          detail: str, evidence: tuple[str, ...] = ()) -> QualityGate:
    return QualityGate(id_, title, status, severity, detail, evidence)


def field_coverage_gates(brief: dict) -> list[QualityGate]:
    fields = brief.get("extraction", {}).get("fields", {})
    gates: list[QualityGate] = []
    for key in REQUIRED_FIELD_KEYS:
        present = key in fields
        gates.append(
            _gate(
                f"field-{key}",
                f"Required field: {key.replace('_', ' ')}",
                "pass" if present else "fail",
                "high" if not present else "info",
                (
                    "Field was extracted and can be reviewed."
                    if present
                    else "Field is missing; comparison prefill and final review must stay blocked."
                ),
                (f"field:{key}",),
            )
        )
    rate_fields = {"contract_rate", "posted_rate", "contract_discount", "offered_rate"}
    found_rates = sorted(rate_fields & set(fields))
    gates.append(
        _gate(
            "rate-context",
            "Rate context",
            "pass" if len(found_rates) >= 2 else "review",
            "medium" if len(found_rates) < 2 else "info",
            f"Found rate fields: {', '.join(found_rates) if found_rates else 'none'}.",
            tuple(f"field:{key}" for key in found_rates),
        )
    )
    return gates


def evidence_quality_gates(normalized_packet: dict) -> list[QualityGate]:
    quality = normalized_packet.get("quality", {})
    gates = [
        _gate(
            "normalized-spans",
            "Normalized text spans",
            "pass" if normalized_packet.get("span_count", 0) > 0 else "fail",
            "high" if normalized_packet.get("span_count", 0) == 0 else "info",
            f"{normalized_packet.get('span_count', 0)} text spans were normalized.",
        ),
        _gate(
            "money-detected",
            "Money amount detected",
            "pass" if quality.get("has_money") else "review",
            "medium" if not quality.get("has_money") else "info",
            "Mortgage review usually needs a balance or payment amount.",
        ),
        _gate(
            "rate-detected",
            "Rate detected",
            "pass" if quality.get("has_rate") else "review",
            "medium" if not quality.get("has_rate") else "info",
            "Mortgage review usually needs one or more interest rates.",
        ),
        _gate(
            "low-confidence-lines",
            "Low-confidence spans",
            "review" if quality.get("low_confidence_span_ids") else "pass",
            "medium" if quality.get("low_confidence_span_ids") else "info",
            f"{len(quality.get('low_confidence_span_ids') or [])} low-confidence spans were found.",
            tuple(quality.get("low_confidence_span_ids") or ()),
        ),
    ]
    return gates


def mortgage_reasoning_gates(brief: dict, math_audit: dict, packet: dict) -> list[QualityGate]:
    risks = brief.get("risk_assessment", {}).get("risks", [])
    high_risks = [risk.get("id") for risk in risks if risk.get("severity") == "high"]
    gates = [
        _gate(
            "brief-readiness",
            "Contract brief readiness",
            "pass" if brief.get("readiness", {}).get("state") != "blocked" else "fail",
            "high" if brief.get("readiness", {}).get("state") == "blocked" else "info",
            f"Readiness state: {brief.get('readiness', {}).get('state')}.",
            tuple(brief.get("readiness", {}).get("missing_required", [])),
        ),
        _gate(
            "math-confidence",
            "Math audit confidence",
            "pass" if math_audit.get("confidence", {}).get("level") == "reviewable" else "review",
            "medium" if math_audit.get("confidence", {}).get("level") != "reviewable" else "info",
            f"Math confidence: {math_audit.get('confidence', {}).get('level')}.",
            tuple(math_audit.get("confidence", {}).get("missing_scenario_ids") or ()),
        ),
        _gate(
            "high-risks",
            "High-risk findings",
            "review" if high_risks else "pass",
            "high" if high_risks else "info",
            f"{len(high_risks)} high-risk findings need review.",
            tuple(high_risks),
        ),
        _gate(
            "lender-packet",
            "Lender packet signoff",
            "pass" if packet.get("signoff", {}).get("can_send_to_lender") else "review",
            "medium" if not packet.get("signoff", {}).get("can_send_to_lender") else "info",
            "The generated lender packet can be sent for confirmation." if packet.get("signoff", {}).get("can_send_to_lender")
            else "The lender packet still has blocking gates.",
        ),
    ]
    return gates


def score_gates(gates: list[QualityGate]) -> dict:
    weights = {"info": 0, "medium": 12, "high": 25}
    penalty = 0
    fail_count = 0
    review_count = 0
    for gate in gates:
        if gate.status == "pass":
            continue
        if gate.status == "fail":
            fail_count += 1
        if gate.status == "review":
            review_count += 1
        penalty += weights.get(gate.severity, 8)
    score = max(0, 100 - penalty)
    if fail_count:
        level = "blocked"
    elif score >= 85:
        level = "reviewable"
    elif score >= 65:
        level = "needs_review"
    else:
        level = "weak"
    return {
        "score": score,
        "level": level,
        "fail_count": fail_count,
        "review_count": review_count,
        "gate_count": len(gates),
    }


def best_next_actions(gates: list[QualityGate], dependency_plan: dict) -> list[dict]:
    actions = []
    for gate in gates:
        if gate.status == "pass":
            continue
        if gate.id.startswith("field-"):
            actions.append(
                {
                    "id": f"action-{gate.id}",
                    "priority": "high",
                    "title": f"Recover {gate.title.lower()}",
                    "detail": "Use the original document, a stronger parser profile, or manual reviewer correction.",
                    "evidence": list(gate.evidence),
                }
            )
        elif gate.id == "low-confidence-lines":
            actions.append(
                {
                    "id": "action-review-low-confidence",
                    "priority": "medium",
                    "title": "Review low-confidence OCR spans",
                    "detail": "Compare low-confidence spans with the source image before using extracted values.",
                    "evidence": list(gate.evidence),
                }
            )
        elif gate.id == "math-confidence":
            actions.append(
                {
                    "id": "action-complete-math-inputs",
                    "priority": "medium",
                    "title": "Complete mortgage math inputs",
                    "detail": "Collect the missing fields needed for penalty or payment estimates.",
                    "evidence": list(gate.evidence),
                }
            )
    top_profiles = dependency_plan.get("recommended_chain", [])[:2]
    for profile in top_profiles:
        if profile.get("can_run_now"):
            continue
        actions.append(
            {
                "id": f"action-optional-{profile.get('dependency_key')}",
                "priority": "low",
                "title": f"Optional adapter profile available: {profile.get('profile_key')}",
                "detail": "This may improve source parsing if installed deliberately from the optional requirements file.",
                "evidence": [profile.get("profile_key")],
            }
        )
    seen = set()
    deduped = []
    for action in actions:
        if action["id"] in seen:
            continue
        seen.add(action["id"])
        deduped.append(action)
    return deduped[:20]


def evaluate_normalized_packet(packet: dict) -> dict:
    pages = packet.get("ocr_pages") or []
    if not pages:
        raise AdapterQualityHarnessError("Normalized packet has no OCR pages")
    try:
        brief = create_contract_brief(pages, filename=f"{packet.get('adapter', 'adapter')}-normalized.txt")
        math_audit = build_contract_math_audit_from_brief(brief)
        lender_packet = build_lender_packet_from_brief(brief)
        dependency_plan = build_dependency_adapter_plan_from_brief(brief)
    except Exception as exc:
        raise AdapterQualityHarnessError("Could not evaluate normalized packet") from exc
    gates = (
        evidence_quality_gates(packet)
        + field_coverage_gates(brief)
        + mortgage_reasoning_gates(brief, math_audit, lender_packet)
    )
    score = score_gates(gates)
    return {
        "provider": "adapter-quality-harness-v15",
        "adapter": packet.get("adapter"),
        "score": score,
        "gates": [gate.public() for gate in gates],
        "next_actions": best_next_actions(gates, dependency_plan),
        "brief_summary": {
            "provider": brief.get("provider"),
            "readiness": brief.get("readiness"),
            "risk_count": brief.get("risk_assessment", {}).get("risk_count"),
            "classification": brief.get("classification"),
        },
        "math_summary": {
            "provider": math_audit.get("provider"),
            "confidence": math_audit.get("confidence"),
            "penalty_scenario_count": len(math_audit.get("penalty_scenarios", [])),
        },
        "dependency_summary": {
            "provider": dependency_plan.get("provider"),
            "top_profiles": [item.get("profile_key") for item in dependency_plan.get("recommended_chain", [])[:3]],
        },
        "notice": "Adapter quality is a local review score, not a guarantee that OCR is correct.",
    }


def evaluate_adapter_payload(payload: Any, adapter: str | None = None) -> dict:
    try:
        packet = normalize_adapter_payload(payload, adapter)
    except AdapterNormalizationError:
        raise
    except Exception as exc:
        raise AdapterQualityHarnessError("Could not normalize adapter payload") from exc
    validation = validate_normalized_packet(packet)
    preview = preview_adapter_payload(payload, adapter)
    evaluation = evaluate_normalized_packet(packet)
    return {
        "provider": "adapter-payload-evaluation-v15",
        "adapter": packet.get("adapter"),
        "preview": preview,
        "validation": validation,
        "evaluation": evaluation,
        "ocr_pages": packet.get("ocr_pages", []),
        "quality": packet.get("quality", {}),
    }
