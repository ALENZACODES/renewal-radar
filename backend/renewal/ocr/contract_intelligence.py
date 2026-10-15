"""V12 deterministic mortgage contract intelligence.

This module builds on V11 document understanding. It does not run an LLM, does
not infer lender-only facts, and does not store OCR text. Its job is to convert
extracted fields, clauses, calculations and review checks into an evidence graph,
plain-language risks, lender questions and deterministic answers to common
Canadian mortgage contract questions.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from .document_understanding import understand_ocr_document
from .fields import OCRFieldError, redact_sensitive_text


class ContractIntelligenceError(ValueError):
    """The contract-intelligence request cannot be processed safely."""


@dataclass(frozen=True)
class EvidenceNode:
    id: str
    kind: str
    label: str
    value: Any
    page: int | None
    confidence: str
    source: str
    excerpt: str | None = None
    warnings: tuple[str, ...] = ()

    def public(self) -> dict:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class EvidenceEdge:
    source: str
    target: str
    relation: str
    detail: str

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RiskItem:
    id: str
    severity: str
    score: int
    title: str
    detail: str
    evidence: tuple[str, ...]
    actions: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        data["actions"] = list(self.actions)
        return data


@dataclass(frozen=True)
class QuestionProfile:
    topic: str
    label: str
    patterns: tuple[str, ...]
    field_keys: tuple[str, ...] = ()
    clause_keys: tuple[str, ...] = ()
    check_keys: tuple[str, ...] = ()


REQUIRED_COMPARISON_FIELDS = (
    "balance",
    "offered_rate",
    "amortization_months",
    "maturity_date",
)

RATE_FIELDS = (
    "contract_rate",
    "posted_rate",
    "contract_discount",
    "current_rate",
    "offered_rate",
)

DATE_FIELDS = (
    "mortgage_start_date",
    "maturity_date",
)

TERM_FIELDS = (
    "term_months",
    "amortization_months",
)


def question_profiles() -> tuple[QuestionProfile, ...]:
    return (
        QuestionProfile(
            "contract_rate",
            "Contract rate",
            (
                r"\bcontract\s+rate\b",
                r"\brate\s+in\s+(?:my\s+)?contract\b",
                r"\bregistered\s+rate\b",
            ),
            field_keys=("contract_rate",),
            clause_keys=("contract_rate_language",),
        ),
        QuestionProfile(
            "posted_rate_discount",
            "Posted rate and contract discount",
            (
                r"\bposted\s+rate\b",
                r"\bcontract\s+discount\b",
                r"\brate\s+discount\b",
                r"\bdiscount\s+(?:from|off)\b",
            ),
            field_keys=("posted_rate", "contract_rate", "contract_discount"),
            clause_keys=("contract_discount_language",),
            check_keys=("contract_rate_discount_math",),
        ),
        QuestionProfile(
            "interest_rate_differential",
            "Interest rate differential",
            (
                r"\binterest\s+rate\s+differential\b",
                r"\bIRD\b",
                r"\bbreak\s+(?:fee|penalty|cost)\b",
                r"\bpenalt(?:y|ies)\b",
            ),
            field_keys=("balance", "contract_rate", "posted_rate", "contract_discount"),
            clause_keys=("interest_rate_differential", "three_month_interest_penalty"),
            check_keys=("contract_rate_discount_math",),
        ),
        QuestionProfile(
            "term",
            "Term",
            (
                r"\bterm\b",
                r"\bhow\s+long\b",
                r"\b60\s+month\b",
                r"\b5\s+year\b",
            ),
            field_keys=("term_months", "mortgage_start_date", "maturity_date"),
            check_keys=("mortgage_date_term_maturity_sequence", "term_not_longer_than_amortization"),
        ),
        QuestionProfile(
            "amortization",
            "Amortization",
            (
                r"\bamorti[sz]ation\b",
                r"\bpay\s+off\b",
                r"\brepayment\s+period\b",
            ),
            field_keys=("amortization_months", "balance", "payment_amount", "frequency"),
            check_keys=("payment_vs_balance_rate_amortization",),
        ),
        QuestionProfile(
            "payment",
            "Payment",
            (
                r"\bpayment\b",
                r"\bmonthly\b",
                r"\bbiweekly\b",
                r"\bfrequency\b",
            ),
            field_keys=("payment_amount", "frequency", "balance", "offered_rate", "amortization_months"),
            clause_keys=("property_tax_collection", "insurance_or_protection"),
            check_keys=("payment_vs_balance_rate_amortization",),
        ),
        QuestionProfile(
            "dates",
            "Mortgage dates",
            (
                r"\bmortgage\s+date\b",
                r"\bdate\s+did\s+(?:the\s+)?mortgage\s+start\b",
                r"\bfunding\s+date\b",
                r"\bstart\s+date\b",
                r"\bmaturity\b",
                r"\bexpiry\b",
            ),
            field_keys=("mortgage_start_date", "maturity_date", "term_months"),
            clause_keys=("mortgage_date_language", "rate_hold_or_expiry"),
            check_keys=("maturity_date_timing", "mortgage_date_term_maturity_sequence"),
        ),
        QuestionProfile(
            "prepayment",
            "Prepayment",
            (
                r"\bprepayment\b",
                r"\bprepay\b",
                r"\blump[- ]?sum\b",
                r"\bextra\s+payment\b",
            ),
            clause_keys=("prepayment_privilege", "interest_rate_differential", "three_month_interest_penalty"),
        ),
        QuestionProfile(
            "risks",
            "Risks and review items",
            (
                r"\brisk\b",
                r"\bwatch\s+out\b",
                r"\bconcern\b",
                r"\bproblem\b",
                r"\bwhat\s+should\s+i\s+ask\b",
            ),
        ),
    )


def _safe_id(*parts: str) -> str:
    material = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    readable = re.sub(r"[^a-z0-9]+", "-", str(parts[0]).lower()).strip("-")[:36]
    return f"{readable}-{digest}" if readable else digest


def _confidence_from_score(score: Any) -> str:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if numeric >= 0.78:
        return "high"
    if numeric >= 0.55:
        return "medium"
    return "low"


def _field_display(extraction: dict, key: str) -> str | None:
    payload = extraction.get("fields", {}).get(key)
    if not payload:
        return None
    return str(payload.get("display_value") or payload.get("value") or "")


def _field_value(extraction: dict, key: str) -> Any:
    return extraction.get("fields", {}).get(key, {}).get("value")


def _node_map(nodes: list[EvidenceNode]) -> dict[str, EvidenceNode]:
    return {node.id: node for node in nodes}


def field_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    fields = understanding.get("extraction", {}).get("fields", {})
    for key, payload in sorted(fields.items()):
        node_id = f"field:{key}"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="field",
                label=str(payload.get("label") or key.replace("_", " ").title()),
                value=payload.get("display_value") or payload.get("value"),
                page=payload.get("page"),
                confidence=str(payload.get("confidence") or _confidence_from_score(payload.get("confidence_score"))),
                source=str(payload.get("source") or "ocr_text"),
                excerpt=payload.get("excerpt"),
                warnings=tuple(payload.get("warnings") or ()),
            )
        )
    return nodes


def clause_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    for clause in understanding.get("clauses", []):
        node_id = f"clause:{clause.get('clause')}"
        confidence = "high" if clause.get("status") == "found" else "low"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="clause",
                label=str(clause.get("label") or clause.get("clause")),
                value=clause.get("status"),
                page=clause.get("page"),
                confidence=confidence,
                source="clause_detector",
                excerpt=clause.get("excerpt"),
                warnings=tuple([clause["risk"]] if clause.get("risk") else ()),
            )
        )
    return nodes


def check_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    for check in understanding.get("consistency_checks", []):
        status = str(check.get("status") or "unknown")
        confidence = "high" if status == "pass" else "medium" if status == "review" else "low"
        nodes.append(
            EvidenceNode(
                id=f"check:{check.get('check')}",
                kind="check",
                label=str(check.get("check") or "consistency_check").replace("_", " ").title(),
                value=status,
                page=None,
                confidence=confidence,
                source="deterministic_check",
                excerpt=check.get("detail"),
                warnings=tuple([status] if status != "pass" else ()),
            )
        )
    return nodes


def section_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    for section in understanding.get("section_map", []):
        nodes.append(
            EvidenceNode(
                id=f"section:{section.get('section')}:{section.get('page')}",
                kind="section",
                label=str(section.get("label") or section.get("section")),
                value=section.get("section"),
                page=section.get("page"),
                confidence=str(section.get("confidence") or "medium"),
                source="section_detector",
                excerpt=section.get("excerpt"),
            )
        )
    return nodes


def detail_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    for index, detail in enumerate(understanding.get("fine_details", [])[:40], 1):
        node_id = f"detail:{detail.get('kind')}:{index}"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="fine_detail",
                label=str(detail.get("label_guess") or detail.get("kind")),
                value=detail.get("value"),
                page=detail.get("page"),
                confidence="medium",
                source="fine_detail_scan",
                excerpt=detail.get("excerpt"),
            )
        )
    return nodes


def calculation_nodes(understanding: dict) -> list[EvidenceNode]:
    nodes = []
    terms = understanding.get("canadian_mortgage_terms", {})
    calculations = terms.get("calculations", {})
    for key, payload in sorted(calculations.items()):
        if not payload:
            continue
        status = str(payload.get("status") or "calculated")
        nodes.append(
            EvidenceNode(
                id=f"calculation:{key}",
                kind="calculation",
                label=key.replace("_", " ").title(),
                value=status,
                page=None,
                confidence="high" if status in {"matches", "pass", "calculated"} else "medium",
                source="canadian_mortgage_terms",
                excerpt=payload.get("explanation") or payload.get("formula_note") or payload.get("formula"),
                warnings=tuple([status] if status in {"review", "inferred_only"} else ()),
            )
        )
    return nodes


def evidence_edges(understanding: dict, nodes: list[EvidenceNode]) -> list[EvidenceEdge]:
    ids = {node.id for node in nodes}
    edges: list[EvidenceEdge] = []
    def add(source: str, target: str, relation: str, detail: str) -> None:
        if source in ids and target in ids:
            edges.append(EvidenceEdge(source, target, relation, detail))

    for field in RATE_FIELDS:
        add(f"field:{field}", "calculation:contract_discount", "feeds_calculation",
            "Rate field participates in posted-rate/contract-rate/discount analysis.")
    add("field:balance", "calculation:payment_estimate", "feeds_calculation",
        "Balance participates in scheduled payment estimate.")
    add("field:offered_rate", "calculation:payment_estimate", "feeds_calculation",
        "Offered rate participates in scheduled payment estimate.")
    add("field:contract_rate", "calculation:payment_estimate", "alternative_rate_input",
        "Contract rate may be used if offered rate is absent.")
    add("field:amortization_months", "calculation:payment_estimate", "feeds_calculation",
        "Remaining amortization controls number of payment periods.")
    add("field:frequency", "calculation:payment_estimate", "feeds_calculation",
        "Payment frequency controls periods per year.")
    for field in DATE_FIELDS + ("term_months",):
        add(f"field:{field}", "calculation:term_timeline", "feeds_calculation",
            "Date or term field participates in timeline analysis.")
    for check in understanding.get("consistency_checks", []):
        check_id = f"check:{check.get('check')}"
        if check.get("check") == "contract_rate_discount_math":
            for field in ("posted_rate", "contract_rate", "contract_discount"):
                add(f"field:{field}", check_id, "checked_by", "Field is tested by contract discount math.")
        if check.get("check") == "mortgage_date_term_maturity_sequence":
            for field in ("mortgage_start_date", "maturity_date", "term_months"):
                add(f"field:{field}", check_id, "checked_by", "Field is tested by term timeline math.")
        if check.get("check") == "payment_vs_balance_rate_amortization":
            for field in ("balance", "offered_rate", "amortization_months", "payment_amount", "frequency"):
                add(f"field:{field}", check_id, "checked_by", "Field is tested by payment sanity check.")
    for clause in understanding.get("clauses", []):
        clause_id = f"clause:{clause.get('clause')}"
        if clause.get("clause") in {"interest_rate_differential", "three_month_interest_penalty"}:
            for field in ("balance", "contract_rate", "posted_rate", "contract_discount", "maturity_date"):
                add(f"field:{field}", clause_id, "context_for", "Field helps interpret penalty language.")
        if clause.get("clause") == "rate_hold_or_expiry":
            add("field:maturity_date", clause_id, "context_for", "Maturity and offer-expiry dates should be reviewed together.")
    return edges


def build_evidence_graph(understanding: dict) -> dict:
    nodes = (
        field_nodes(understanding)
        + clause_nodes(understanding)
        + check_nodes(understanding)
        + section_nodes(understanding)
        + detail_nodes(understanding)
        + calculation_nodes(understanding)
    )
    edges = evidence_edges(understanding, nodes)
    kind_counts: dict[str, int] = {}
    for node in nodes:
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1
    return {
        "nodes": [node.public() for node in nodes],
        "edges": [edge.public() for edge in edges],
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "kind_counts": kind_counts,
            "has_rate_context": any(node.id in {"field:contract_rate", "field:posted_rate"} for node in nodes),
            "has_penalty_context": any(node.id == "clause:interest_rate_differential" and node.value == "found" for node in nodes),
            "has_timeline_context": all(f"field:{key}" in {node.id for node in nodes} for key in ("mortgage_start_date", "maturity_date")),
        },
    }


def _risk(id_: str, severity: str, score: int, title: str,
          detail: str, evidence: tuple[str, ...],
          actions: tuple[str, ...]) -> RiskItem:
    return RiskItem(id_, severity, score, title, detail, evidence, actions)


def _severity(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _check_by_key(understanding: dict) -> dict[str, dict]:
    return {item.get("check"): item for item in understanding.get("consistency_checks", [])}


def _clause_by_key(understanding: dict) -> dict[str, dict]:
    return {item.get("clause"): item for item in understanding.get("clauses", [])}


def _days_until(value: Any) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(str(value)) - date.today()).days
    except ValueError:
        return None


def assess_contract_risks(understanding: dict) -> dict:
    extraction = understanding.get("extraction", {})
    fields = extraction.get("fields", {})
    checks = _check_by_key(understanding)
    clauses = _clause_by_key(understanding)
    risks: list[RiskItem] = []

    missing = [key for key in REQUIRED_COMPARISON_FIELDS if key not in fields]
    if missing:
        risks.append(
            _risk(
                "missing-required-fields",
                "high",
                85,
                "Required comparison fields are missing",
                "The document cannot safely prefill a mortgage comparison until required fields are verified.",
                tuple(f"field:{key}" for key in missing),
                tuple(f"Collect or manually enter {key.replace('_', ' ')}." for key in missing),
            )
        )

    discount_check = checks.get("contract_rate_discount_math")
    if discount_check and discount_check.get("status") == "review":
        risks.append(
            _risk(
                "discount-math-review",
                "high",
                78,
                "Contract discount math does not line up",
                str(discount_check.get("detail") or "Posted rate, contract rate and discount need review."),
                ("check:contract_rate_discount_math", "field:posted_rate", "field:contract_rate", "field:contract_discount"),
                (
                    "Ask the lender whether posted rate, contract rate and discount are from the same term/date.",
                    "Verify the discount from the original mortgage contract or payout statement.",
                ),
            )
        )

    if clauses.get("interest_rate_differential", {}).get("status") == "found":
        risks.append(
            _risk(
                "ird-language-found",
                "medium",
                58,
                "Interest-rate-differential language appears in the document",
                "Fixed-rate break costs may depend on lender-specific comparison rates and discount treatment.",
                ("clause:interest_rate_differential",),
                (
                    "Request a written payout statement before relying on switch savings.",
                    "Ask which comparison rate and date are used for the IRD formula.",
                ),
            )
        )

    if clauses.get("three_month_interest_penalty", {}).get("status") == "found":
        risks.append(
            _risk(
                "three-month-interest-language",
                "medium",
                52,
                "Three-month interest penalty language appears",
                "The document may use a greater-of formula or a product-specific prepayment penalty rule.",
                ("clause:three_month_interest_penalty",),
                (
                    "Confirm whether the penalty is three-month interest, IRD, or the greater of both.",
                    "Ask for a written payout amount as of the intended discharge date.",
                ),
            )
        )

    payment_check = checks.get("payment_vs_balance_rate_amortization")
    if payment_check and payment_check.get("status") == "review":
        risks.append(
            _risk(
                "payment-mismatch",
                "medium",
                55,
                "Payment does not match a simple Canadian mortgage estimate",
                str(payment_check.get("detail") or "Payment requires manual review."),
                ("check:payment_vs_balance_rate_amortization",),
                (
                    "Confirm payment frequency and whether the amount includes taxes or insurance.",
                    "Ask the lender for principal-and-interest payment separately.",
                ),
            )
        )

    timeline_check = checks.get("mortgage_date_term_maturity_sequence")
    if timeline_check and timeline_check.get("status") == "review":
        risks.append(
            _risk(
                "timeline-mismatch",
                "medium",
                56,
                "Mortgage date, term and maturity do not align cleanly",
                str(timeline_check.get("detail") or "Timeline requires manual review."),
                ("check:mortgage_date_term_maturity_sequence",),
                (
                    "Confirm whether the date is funding, registration, interest-adjustment or term-start date.",
                    "Verify the true term start and maturity dates before calculating penalties.",
                ),
            )
        )

    current_rate = _field_value(extraction, "current_rate")
    offered_rate = _field_value(extraction, "offered_rate")
    if current_rate is not None and offered_rate is not None:
        change = float(offered_rate) - float(current_rate)
        if abs(change) >= 1:
            risks.append(
                _risk(
                    "rate-shock",
                    "medium" if change > 0 else "low",
                    50 if change > 0 else 28,
                    "Renewal rate differs materially from current rate",
                    f"The offered rate differs from the current rate by {round(change, 3)} percentage points.",
                    ("field:current_rate", "field:offered_rate"),
                    (
                        "Run payment comparison using the offered rate and remaining amortization.",
                        "Ask whether the lender has a lower retention offer or rate exception process.",
                    ),
                )
            )

    maturity_days = _days_until(_field_value(extraction, "maturity_date"))
    if maturity_days is not None:
        if maturity_days < 0:
            risks.append(
                _risk(
                    "maturity-past",
                    "high",
                    82,
                    "Maturity date appears to be in the past",
                    "The extracted maturity date is already past; the document may be stale or OCR may be wrong.",
                    ("field:maturity_date", "check:maturity_date_timing"),
                    ("Confirm the current renewal status with the lender.",),
                )
            )
        elif maturity_days <= 30:
            risks.append(
                _risk(
                    "maturity-urgent",
                    "medium",
                    60,
                    "Maturity date is close",
                    f"The extracted maturity date is {maturity_days} day(s) away.",
                    ("field:maturity_date",),
                    (
                        "Confirm lender signing deadlines.",
                        "Start switch/refinance paperwork immediately if comparing alternatives.",
                    ),
                )
            )

    for key, title, detail in (
        ("automatic_renewal", "Automatic renewal language appears", "Borrower may renew by default if no action is taken."),
        ("cashback_or_clawback", "Cashback or clawback language appears", "Early discharge may require incentive repayment."),
        ("collateral_charge", "Collateral-charge language appears", "Switching logistics and legal costs may differ."),
        ("insurance_or_protection", "Insurance or protection premium language appears", "Payment may include optional insurance."),
        ("property_tax_collection", "Property-tax language appears", "Payment may include tax amounts."),
        ("blend_and_extend", "Blend-and-extend language appears", "Blended offers can hide embedded break costs."),
    ):
        if clauses.get(key, {}).get("status") == "found":
            risks.append(
                _risk(
                    key,
                    "medium",
                    48,
                    title,
                    detail,
                    (f"clause:{key}",),
                    (clauses[key].get("review_prompt") or "Ask the lender to explain this clause.",),
                )
            )

    score = min(100, sum(item.score for item in risks[:8]))
    risks.sort(key=lambda item: (-item.score, item.id))
    return {
        "risk_score": score,
        "risk_level": _severity(score),
        "risks": [item.public() for item in risks],
        "risk_count": len(risks),
        "high_risk_count": sum(1 for item in risks if item.severity == "high"),
    }


def readiness_assessment(understanding: dict, risks: dict) -> dict:
    extraction = understanding.get("extraction", {})
    fields = extraction.get("fields", {})
    missing = [key for key in REQUIRED_COMPARISON_FIELDS if key not in fields]
    review_status = extraction.get("review_status")
    high_risks = risks.get("high_risk_count", 0)
    score = 100
    score -= len(missing) * 18
    if review_status == "blocked":
        score -= 25
    elif review_status == "review_recommended":
        score -= 12
    score -= min(40, risks.get("risk_score", 0) // 3)
    score = max(0, min(100, score))
    if missing or high_risks:
        state = "blocked"
    elif score >= 72:
        state = "ready_with_review"
    elif score >= 45:
        state = "review_required"
    else:
        state = "not_ready"
    return {
        "state": state,
        "score": score,
        "missing_required": missing,
        "review_status": review_status,
        "can_prefill_comparison": state in {"ready_with_review", "review_required"} and not missing,
        "can_finalize_without_human_review": False,
        "reason": "OCR-derived contract understanding always requires human review before use.",
    }


def lender_questions(understanding: dict, risks: dict) -> list[dict]:
    questions: list[dict] = []
    extraction = understanding.get("extraction", {})
    fields = extraction.get("fields", {})
    def add(topic: str, priority: str, question: str, evidence: tuple[str, ...]) -> None:
        questions.append({
            "topic": topic,
            "priority": priority,
            "question": question,
            "evidence": list(evidence),
        })

    if "contract_rate" in fields or "posted_rate" in fields or "contract_discount" in fields:
        add(
            "contract_discount",
            "high",
            "Are the posted rate, contract rate and contract discount from the same product, term and date?",
            ("field:posted_rate", "field:contract_rate", "field:contract_discount"),
        )
    if any(risk["id"] == "ird-language-found" for risk in risks.get("risks", [])):
        add(
            "interest_rate_differential",
            "high",
            "If the mortgage is discharged before maturity, what comparison rate and discount treatment are used for IRD?",
            ("clause:interest_rate_differential",),
        )
        add(
            "payout_statement",
            "high",
            "Can you provide a written payout statement as of the expected discharge date?",
            ("clause:interest_rate_differential", "field:balance"),
        )
    if "mortgage_start_date" in fields or "maturity_date" in fields:
        add(
            "timeline",
            "medium",
            "Which date is the true term start date: funding, registration, interest-adjustment or first-payment date?",
            ("field:mortgage_start_date", "field:maturity_date", "field:term_months"),
        )
    if "payment_amount" in fields:
        add(
            "payment_breakdown",
            "medium",
            "Does the payment amount include only principal and interest, or also taxes, insurance or other charges?",
            ("field:payment_amount", "field:frequency"),
        )
    for risk in risks.get("risks", []):
        for action in risk.get("actions", [])[:2]:
            add(risk["id"], risk["severity"], action, tuple(risk.get("evidence", [])))
    seen = set()
    output = []
    for item in questions:
        key = (item["topic"], item["question"])
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    output.sort(key=lambda item: (priority_order.get(item["priority"], 3), item["topic"]))
    return output[:30]


def canonicalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", redact_sensitive_text(question or "")).strip()[:500]


def match_question_profile(question: str) -> QuestionProfile:
    normalized = canonicalize_question(question).lower()
    if not normalized:
        raise ContractIntelligenceError("Question is required")
    for profile in question_profiles():
        if any(re.search(pattern, normalized, flags=re.I) for pattern in profile.patterns):
            return profile
    return QuestionProfile(
        "general",
        "General mortgage document question",
        (),
        field_keys=REQUIRED_COMPARISON_FIELDS + RATE_FIELDS + DATE_FIELDS + TERM_FIELDS,
    )


def _sentence_join(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _field_sentence(extraction: dict, key: str) -> str | None:
    value = _field_display(extraction, key)
    if value is None:
        return None
    label = extraction.get("fields", {}).get(key, {}).get("label") or key.replace("_", " ")
    suffix = "%" if key in RATE_FIELDS and not str(value).endswith("%") else ""
    if key in {"term_months", "amortization_months"}:
        suffix = " months"
    return f"{label}: {value}{suffix}."


def _clause_sentence(understanding: dict, key: str) -> str | None:
    clause = _clause_by_key(understanding).get(key)
    if not clause:
        return None
    if clause.get("status") == "found":
        return f"{clause.get('label')} was found; {clause.get('review_prompt')}"
    if clause.get("risk"):
        return f"{clause.get('label')} was not found; {clause.get('risk')}"
    return None


def _check_sentence(understanding: dict, key: str) -> str | None:
    check = _check_by_key(understanding).get(key)
    if not check:
        return None
    return f"{str(check.get('check')).replace('_', ' ').title()}: {check.get('status')}. {check.get('detail')}"


def answer_contract_question(understanding: dict, question: str,
                             risks: dict | None = None,
                             graph: dict | None = None) -> dict:
    profile = match_question_profile(question)
    extraction = understanding.get("extraction", {})
    risks = risks or assess_contract_risks(understanding)
    graph = graph or build_evidence_graph(understanding)
    evidence_ids: list[str] = []
    parts: list[str] = []

    if profile.topic == "risks":
        top = risks.get("risks", [])[:5]
        if not top:
            parts.append("No deterministic high-priority risk was found, but OCR fields still require manual verification.")
        else:
            parts.append("Main review risks: " + "; ".join(f"{item['title']} ({item['severity']})" for item in top) + ".")
            for item in top:
                evidence_ids.extend(item.get("evidence", []))
    else:
        for key in profile.field_keys:
            sentence = _field_sentence(extraction, key)
            if sentence:
                parts.append(sentence)
                evidence_ids.append(f"field:{key}")
        for key in profile.clause_keys:
            sentence = _clause_sentence(understanding, key)
            if sentence:
                parts.append(sentence)
                evidence_ids.append(f"clause:{key}")
        for key in profile.check_keys:
            sentence = _check_sentence(understanding, key)
            if sentence:
                parts.append(sentence)
                evidence_ids.append(f"check:{key}")

    if profile.topic == "posted_rate_discount":
        calc = understanding.get("canadian_mortgage_terms", {}).get("calculations", {}).get("contract_discount")
        if calc:
            parts.append(
                "Discount math: "
                + (calc.get("explanation") or "posted rate minus contract rate gives the implied discount.")
            )
            evidence_ids.append("calculation:contract_discount")
    if profile.topic == "payment":
        calc = understanding.get("canadian_mortgage_terms", {}).get("calculations", {}).get("payment_estimate")
        if calc:
            parts.append(
                f"Canadian fixed-rate estimate: {calc.get('estimated_payment')} per {calc.get('frequency')} payment, "
                f"using {calc.get('periods_per_year')} periods per year."
            )
            evidence_ids.append("calculation:payment_estimate")
    if profile.topic == "term":
        calc = understanding.get("canadian_mortgage_terms", {}).get("calculations", {}).get("term_timeline")
        if calc:
            parts.append(
                f"Timeline check: {calc.get('months_between')} months between mortgage start and maturity; "
                f"status {calc.get('status')}."
            )
            evidence_ids.append("calculation:term_timeline")
    if profile.topic == "interest_rate_differential":
        parts.append(
            "IRD is lender-specific; this tool flags the language and asks for the written payout statement rather than claiming a binding penalty."
        )

    if not parts:
        parts.append(
            "I could not answer that from the extracted evidence. Ask for the original lender document or enter a manual correction."
        )

    known_nodes = _node_map([EvidenceNode(**node) for node in graph.get("nodes", [])])
    deduped = []
    for evidence_id in evidence_ids:
        if evidence_id in known_nodes and evidence_id not in deduped:
            deduped.append(evidence_id)
    confidence = "high" if deduped and not extraction.get("missing_required") else "medium" if deduped else "low"
    return {
        "question": canonicalize_question(question),
        "topic": profile.topic,
        "label": profile.label,
        "answer": _sentence_join(parts),
        "evidence": deduped[:12],
        "confidence": confidence,
        "caveats": [
            "OCR-derived answers require human verification against the source document.",
            "Penalty and payout figures must come from the lender's written payout statement.",
        ],
    }


def create_contract_brief(pages: list[Any], *, filename: str = "ocr.txt",
                          corrections: dict[str, Any] | None = None,
                          min_confidence: float = 0.0,
                          question: str | None = None) -> dict:
    try:
        understanding = understand_ocr_document(
            pages,
            filename=filename,
            corrections=corrections,
            min_confidence=min_confidence,
        )
    except OCRFieldError:
        raise
    except Exception as exc:
        raise ContractIntelligenceError("Could not understand OCR document") from exc
    graph = build_evidence_graph(understanding)
    risks = assess_contract_risks(understanding)
    readiness = readiness_assessment(understanding, risks)
    questions = lender_questions(understanding, risks)
    result = {
        "provider": "deterministic-contract-intelligence-v12",
        "filename": str(filename or "ocr.txt")[:120],
        "classification": understanding.get("classification"),
        "understanding_score": understanding.get("understanding_score"),
        "readiness": readiness,
        "risk_assessment": risks,
        "lender_questions": questions,
        "evidence_graph": graph,
        "summary": understanding.get("summary", []),
        "canadian_mortgage_terms": understanding.get("canadian_mortgage_terms", {}),
        "review_questions": understanding.get("review_questions", []),
        "extraction": understanding.get("extraction", {}),
        "raw_ocr_stored": False,
        "notice": "Contract intelligence is a deterministic review aid, not lender certification or legal advice.",
    }
    if question is not None:
        result["answer"] = answer_contract_question(understanding, question, risks, graph)
    return result
