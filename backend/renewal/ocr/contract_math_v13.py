"""V13 Canadian mortgage contract math and disclosure audit.

This module is intentionally dependency-free. It takes a V12 contract brief and
turns the extracted fields, clauses, dates and calculations into a local audit
packet: formula walkthroughs, penalty estimates, renewal timing checks,
disclosure prompts and field dependencies. It does not claim lender-certified
payout amounts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .contract_intelligence import create_contract_brief


CENT = Decimal("0.01")
BASIS_POINT = Decimal("0.01")
MAX_TIMELINE_MONTHS = 600


class ContractMathAuditError(ValueError):
    """Contract math audit input was not usable."""


@dataclass(frozen=True)
class FormulaStep:
    id: str
    label: str
    formula: str
    inputs: tuple[str, ...]
    output: Any
    explanation: str
    evidence: tuple[str, ...]
    caveat: str

    def public(self) -> dict:
        data = asdict(self)
        data["inputs"] = list(self.inputs)
        data["evidence"] = list(self.evidence)
        return data


@dataclass(frozen=True)
class PenaltyScenario:
    id: str
    label: str
    amount: float | None
    formula: str
    inputs: dict[str, Any]
    status: str
    explanation: str
    evidence: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


@dataclass(frozen=True)
class DisclosurePrompt:
    id: str
    priority: str
    question: str
    why: str
    evidence: tuple[str, ...]

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").replace("%", ""))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _rate_fraction(rate_percent: Any) -> Decimal | None:
    rate = _decimal(rate_percent)
    if rate is None:
        return None
    return rate / Decimal("100")


def _field(brief: dict, key: str) -> dict:
    return brief.get("extraction", {}).get("fields", {}).get(key, {})


def _value(brief: dict, key: str) -> Any:
    return _field(brief, key).get("value")


def _display(brief: dict, key: str) -> str | None:
    payload = _field(brief, key)
    if not payload:
        return None
    value = payload.get("display_value")
    if value is None:
        value = payload.get("value")
    return str(value) if value is not None else None


def _evidence_for(*field_keys: str) -> tuple[str, ...]:
    return tuple(f"field:{key}" for key in field_keys)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, min(months, MAX_TIMELINE_MONTHS))


def remaining_months_until_maturity(brief: dict, as_of: date | None = None) -> int | None:
    maturity = _parse_date(_value(brief, "maturity_date"))
    if maturity is None:
        return None
    as_of = as_of or date.today()
    return months_between(as_of, maturity)


def term_months_from_dates(brief: dict) -> int | None:
    start = _parse_date(_value(brief, "mortgage_start_date"))
    maturity = _parse_date(_value(brief, "maturity_date"))
    if start is None or maturity is None:
        return None
    return months_between(start, maturity)


def annual_interest_amount(balance: Any, rate_percent: Any) -> Decimal | None:
    principal = _decimal(balance)
    rate = _rate_fraction(rate_percent)
    if principal is None or rate is None:
        return None
    return principal * rate


def three_month_interest_amount(balance: Any, rate_percent: Any) -> Decimal | None:
    annual = annual_interest_amount(balance, rate_percent)
    if annual is None:
        return None
    return annual * Decimal("0.25")


def simple_ird_amount(balance: Any, contract_rate: Any,
                      comparison_rate: Any, remaining_months: Any) -> Decimal | None:
    principal = _decimal(balance)
    contract = _rate_fraction(contract_rate)
    comparison = _rate_fraction(comparison_rate)
    months = _decimal(remaining_months)
    if principal is None or contract is None or comparison is None or months is None:
        return None
    spread = max(Decimal("0"), contract - comparison)
    return principal * spread * (months / Decimal("12"))


def posted_discount_comparison_rate(current_posted_rate: Any, original_discount: Any) -> Decimal | None:
    posted = _decimal(current_posted_rate)
    discount = _decimal(original_discount)
    if posted is None or discount is None:
        return None
    return max(Decimal("0"), posted - discount)


def field_dependency_map(brief: dict) -> dict:
    fields = brief.get("extraction", {}).get("fields", {})
    present = set(fields)
    dependencies = {
        "contract_discount": {
            "requires": ["posted_rate", "contract_rate"],
            "optional": ["contract_discount"],
            "reason": "Posted rate minus contract rate gives the implied discount when all values share the same date and product context.",
        },
        "payment_estimate": {
            "requires": ["balance", "offered_rate", "amortization_months", "frequency"],
            "optional": ["payment_amount"],
            "reason": "Canadian payment estimates need balance, rate, remaining amortization and payment frequency.",
        },
        "term_timeline": {
            "requires": ["mortgage_start_date", "maturity_date"],
            "optional": ["term_months"],
            "reason": "Mortgage date and maturity date anchor the term and renewal timing.",
        },
        "three_month_interest": {
            "requires": ["balance", "contract_rate"],
            "optional": ["payment_amount"],
            "reason": "Three-month interest is principal times contract-rate interest for one quarter of a year.",
        },
        "interest_rate_differential": {
            "requires": ["balance", "contract_rate", "maturity_date"],
            "optional": ["posted_rate", "contract_discount", "comparison_rate", "remaining_months"],
            "reason": "IRD requires lender-specific comparison-rate logic; local math can only estimate scenarios.",
        },
    }
    result = {}
    for key, spec in dependencies.items():
        required = spec["requires"]
        optional = spec["optional"]
        missing_required = [name for name in required if name not in present]
        available_optional = [name for name in optional if name in present]
        result[key] = {
            "requires": required,
            "optional": optional,
            "missing_required": missing_required,
            "available_optional": available_optional,
            "ready": not missing_required,
            "reason": spec["reason"],
            "evidence": _evidence_for(*(name for name in required + optional if name in present)),
        }
    return result


def formula_walkthroughs(brief: dict, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    steps: list[FormulaStep] = []
    posted = _decimal(_value(brief, "posted_rate"))
    contract = _decimal(_value(brief, "contract_rate"))
    discount = _decimal(_value(brief, "contract_discount"))
    if posted is not None and contract is not None:
        implied = posted - contract
        explanation = "Posted rate minus contract rate gives the implied contract discount."
        if discount is not None:
            diff = abs(implied - discount)
            explanation += f" Document discount differs by {diff.quantize(BASIS_POINT)} percentage points."
        steps.append(
            FormulaStep(
                id="formula-contract-discount",
                label="Contract discount",
                formula="posted_rate - contract_rate = implied_discount",
                inputs=("posted_rate", "contract_rate", "contract_discount"),
                output=float(implied.quantize(BASIS_POINT)),
                explanation=explanation,
                evidence=_evidence_for("posted_rate", "contract_rate", "contract_discount"),
                caveat="Only compare rates from the same term, product and date.",
            )
        )

    balance = _decimal(_value(brief, "balance"))
    rate = _decimal(_value(brief, "contract_rate"))
    three_month = three_month_interest_amount(balance, rate)
    if three_month is not None:
        steps.append(
            FormulaStep(
                id="formula-three-month-interest",
                label="Three months interest",
                formula="balance * (contract_rate / 100) * 3 / 12",
                inputs=("balance", "contract_rate"),
                output=_money(three_month),
                explanation="This estimates one quarter of a year of interest at the extracted contract rate.",
                evidence=_evidence_for("balance", "contract_rate"),
                caveat="Lenders may define the rate base, balance date or compounding details differently.",
            )
        )

    date_months = term_months_from_dates(brief)
    document_term = _decimal(_value(brief, "term_months"))
    if date_months is not None:
        status = "matches"
        if document_term is not None and abs(date_months - int(document_term)) > 2:
            status = "review"
        steps.append(
            FormulaStep(
                id="formula-term-timeline",
                label="Mortgage date to maturity",
                formula="months_between(mortgage_start_date, maturity_date)",
                inputs=("mortgage_start_date", "maturity_date", "term_months"),
                output={"months_between": date_months, "status": status},
                explanation="The start date and maturity date should roughly align with the stated term.",
                evidence=_evidence_for("mortgage_start_date", "maturity_date", "term_months"),
                caveat="Interest adjustment date, funding date and registration date may not mean the same thing.",
            )
        )

    remaining = remaining_months_until_maturity(brief, as_of)
    if remaining is not None:
        steps.append(
            FormulaStep(
                id="formula-remaining-term",
                label="Remaining months to maturity",
                formula="months_between(as_of_date, maturity_date)",
                inputs=("as_of_date", "maturity_date"),
                output={"as_of": as_of.isoformat(), "remaining_months": remaining},
                explanation="This is a calendar estimate used to size penalty scenarios and renewal urgency.",
                evidence=_evidence_for("maturity_date"),
                caveat="The lender payout statement controls the exact payout date and per-diem interest.",
            )
        )
    return [step.public() for step in steps]


def penalty_scenarios(brief: dict, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    balance = _value(brief, "balance")
    contract_rate = _value(brief, "contract_rate")
    posted_rate = _value(brief, "posted_rate")
    discount = _value(brief, "contract_discount")
    remaining = remaining_months_until_maturity(brief, as_of)
    scenarios: list[PenaltyScenario] = []

    three_month = three_month_interest_amount(balance, contract_rate)
    scenarios.append(
        PenaltyScenario(
            id="three-month-interest",
            label="Three-month interest estimate",
            amount=_money(three_month),
            formula="balance * (contract_rate / 100) * 0.25",
            inputs={"balance": _display(brief, "balance"), "contract_rate": _display(brief, "contract_rate")},
            status="estimated" if three_month is not None else "missing_inputs",
            explanation=(
                "A common penalty comparison is roughly three months of interest."
                if three_month is not None
                else "Balance and contract rate are required for this scenario."
            ),
            evidence=_evidence_for("balance", "contract_rate"),
        )
    )

    if remaining is not None and posted_rate is not None and discount is not None:
        comparison_rate = posted_discount_comparison_rate(posted_rate, discount)
        ird = simple_ird_amount(balance, contract_rate, comparison_rate, remaining)
        scenarios.append(
            PenaltyScenario(
                id="posted-discount-ird",
                label="Posted-rate-minus-discount IRD scenario",
                amount=_money(ird),
                formula="balance * max(contract_rate - (current_posted_rate - original_discount), 0) * remaining_months / 12",
                inputs={
                    "balance": _display(brief, "balance"),
                    "contract_rate": _display(brief, "contract_rate"),
                    "posted_rate": _display(brief, "posted_rate"),
                    "contract_discount": _display(brief, "contract_discount"),
                    "remaining_months": remaining,
                    "comparison_rate_percent": float(comparison_rate.quantize(BASIS_POINT)) if comparison_rate is not None else None,
                },
                status="estimated" if ird is not None else "missing_inputs",
                explanation="This scenario mirrors a common Canadian posted-rate discount framing, but the lender's formula may differ.",
                evidence=_evidence_for("balance", "contract_rate", "posted_rate", "contract_discount", "maturity_date"),
            )
        )
    else:
        scenarios.append(
            PenaltyScenario(
                id="posted-discount-ird",
                label="Posted-rate-minus-discount IRD scenario",
                amount=None,
                formula="balance * max(contract_rate - comparison_rate, 0) * remaining_months / 12",
                inputs={
                    "missing": [
                        key
                        for key, value in {
                            "balance": balance,
                            "contract_rate": contract_rate,
                            "posted_rate": posted_rate,
                            "contract_discount": discount,
                            "maturity_date": _value(brief, "maturity_date"),
                        }.items()
                        if value is None
                    ]
                },
                status="missing_inputs",
                explanation="The document does not expose enough fields for a posted-rate-discount IRD scenario.",
                evidence=(),
            )
        )

    estimated = [item for item in scenarios if item.amount is not None]
    if estimated:
        higher = max(estimated, key=lambda item: item.amount or 0)
        scenarios.append(
            PenaltyScenario(
                id="greater-of-visible-scenarios",
                label="Greater-of visible scenarios",
                amount=higher.amount,
                formula="max(visible_penalty_scenarios)",
                inputs={"scenario_ids": [item.id for item in estimated]},
                status="review_only",
                explanation=f"The largest visible local estimate is {higher.label}; ask the lender for a written payout statement.",
                evidence=tuple(e for item in estimated for e in item.evidence),
            )
        )
    return [scenario.public() for scenario in scenarios]


def renewal_disclosure_timeline(brief: dict, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    maturity = _parse_date(_value(brief, "maturity_date"))
    offer_expiry = None
    for clause in brief.get("evidence_graph", {}).get("nodes", []):
        if clause.get("id") == "clause:rate_hold_or_expiry":
            offer_expiry = clause.get("excerpt")
            break
    if maturity is None:
        return {
            "status": "missing_maturity_date",
            "as_of": as_of.isoformat(),
            "maturity_date": None,
            "days_to_maturity": None,
            "fcac_renewal_notice_window": "Federally regulated lenders generally provide renewal statements at least 21 days before term end.",
            "offer_expiry_evidence": offer_expiry,
        }
    days = (maturity - as_of).days
    if days < 0:
        status = "past_maturity"
    elif days <= 21:
        status = "inside_21_day_window"
    elif days <= 60:
        status = "renewal_window_open"
    else:
        status = "early_review"
    return {
        "status": status,
        "as_of": as_of.isoformat(),
        "maturity_date": maturity.isoformat(),
        "days_to_maturity": days,
        "fcac_renewal_notice_window": "Federally regulated lenders generally provide renewal statements at least 21 days before term end.",
        "offer_expiry_evidence": offer_expiry,
    }


def disclosure_prompts(brief: dict) -> list[dict]:
    risks = {risk.get("id"): risk for risk in brief.get("risk_assessment", {}).get("risks", [])}
    fields = brief.get("extraction", {}).get("fields", {})
    prompts = [
        DisclosurePrompt(
            id="ask-ird-method",
            priority="high" if "ird-language-found" in risks else "medium",
            question="Which exact IRD formula, comparison rate and comparison date will the lender use?",
            why="FCAC guidance emphasizes clear disclosure of the method and factors used for prepayment charges.",
            evidence=("clause:interest_rate_differential", "field:contract_rate", "field:posted_rate"),
        ),
        DisclosurePrompt(
            id="ask-discount-treatment",
            priority="high" if "contract_discount" in fields else "medium",
            question="Does the original contract discount affect payout, renewal, blend, or switch calculations?",
            why="Posted-rate discounts can materially change Canadian IRD estimates.",
            evidence=("field:contract_discount", "calculation:contract_discount"),
        ),
        DisclosurePrompt(
            id="ask-payout-statement",
            priority="high",
            question="Can the lender provide a written payout statement for the planned payout date?",
            why="The app can estimate scenarios, but only the lender can certify payout balance, per-diem interest and discharge fees.",
            evidence=("field:balance", "field:maturity_date"),
        ),
        DisclosurePrompt(
            id="ask-renewal-deadline",
            priority="medium",
            question="What is the last date to accept, decline, or change the renewal offer?",
            why="Renewal timing affects whether the borrower can shop, switch, or avoid automatic renewal.",
            evidence=("field:maturity_date", "clause:rate_hold_or_expiry", "clause:automatic_renewal"),
        ),
    ]
    missing_required = brief.get("readiness", {}).get("missing_required", [])
    if missing_required:
        prompts.insert(
            0,
            DisclosurePrompt(
                id="collect-required-fields",
                priority="critical",
                question="Can the original document or lender confirm the missing required fields?",
                why="A comparison cannot be prefilled safely without the required mortgage values.",
                evidence=tuple(f"field:{key}" for key in missing_required),
            ),
        )
    return [prompt.public() for prompt in prompts]


def confidence_summary(brief: dict, scenarios: list[dict], walkthroughs: list[dict]) -> dict:
    missing_required = brief.get("readiness", {}).get("missing_required", [])
    high_risks = [
        risk.get("id")
        for risk in brief.get("risk_assessment", {}).get("risks", [])
        if risk.get("severity") == "high"
    ]
    missing_scenarios = [item["id"] for item in scenarios if item["status"] == "missing_inputs"]
    if missing_required or high_risks:
        level = "low"
    elif missing_scenarios:
        level = "medium"
    else:
        level = "reviewable"
    return {
        "level": level,
        "walkthrough_count": len(walkthroughs),
        "penalty_scenario_count": len(scenarios),
        "missing_required": missing_required,
        "high_risk_ids": high_risks,
        "missing_scenario_ids": missing_scenarios,
        "human_review_required": True,
    }


def build_contract_math_audit_from_brief(brief: dict, *,
                                         as_of: date | None = None) -> dict:
    if not isinstance(brief, dict) or brief.get("provider") != "deterministic-contract-intelligence-v12":
        raise ContractMathAuditError("Expected a V12 contract-intelligence brief")
    as_of = as_of or date.today()
    walkthroughs = formula_walkthroughs(brief, as_of)
    scenarios = penalty_scenarios(brief, as_of)
    dependencies = field_dependency_map(brief)
    return {
        "provider": "canadian-contract-math-audit-v13",
        "filename": brief.get("filename"),
        "as_of": as_of.isoformat(),
        "formula_walkthroughs": walkthroughs,
        "penalty_scenarios": scenarios,
        "field_dependencies": dependencies,
        "disclosure_prompts": disclosure_prompts(brief),
        "renewal_timeline": renewal_disclosure_timeline(brief, as_of),
        "confidence": confidence_summary(brief, scenarios, walkthroughs),
        "source_brief_provider": brief.get("provider"),
        "notice": "All amounts are local review estimates; lender statements and contract text control.",
    }


def create_contract_math_audit(pages: list[Any], *, filename: str = "ocr.txt",
                               corrections: dict[str, Any] | None = None,
                               min_confidence: float = 0.0,
                               question: str | None = None,
                               as_of: date | None = None) -> dict:
    brief = create_contract_brief(
        pages,
        filename=filename,
        corrections=corrections,
        min_confidence=min_confidence,
        question=question,
    )
    return build_contract_math_audit_from_brief(brief, as_of=as_of)
