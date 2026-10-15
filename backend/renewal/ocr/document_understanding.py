"""V11 mortgage-document understanding on top of OCR text.

OCR is only a reading layer. This module adds a deterministic understanding
pass that classifies the document, finds sections and clauses, extracts fine
financial details, and checks whether key numbers appear internally consistent.
It stays privacy-conscious: snippets are redacted and raw OCR text is not
returned in the public result.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .fields import (
    OCRFieldError,
    OCRTextPage,
    extract_ocr_fields,
    flatten_ocr_text,
    prepare_pages,
    redact_sensitive_text,
)
from .mortgage_terms import explain_extracted_terms

MONEY = Decimal("0.01")
MAX_FINE_DETAILS = 80
MAX_SECTIONS = 30
MAX_REVIEW_QUESTIONS = 40


@dataclass(frozen=True)
class DocumentSignal:
    key: str
    label: str
    patterns: tuple[str, ...]
    weight: int


@dataclass(frozen=True)
class ClauseSpec:
    key: str
    label: str
    patterns: tuple[str, ...]
    review_prompt: str
    risk_if_present: str | None = None
    risk_if_absent: str | None = None


@dataclass(frozen=True)
class SectionSpec:
    key: str
    label: str
    patterns: tuple[str, ...]


def document_signals() -> tuple[DocumentSignal, ...]:
    return (
        DocumentSignal(
            "renewal_offer",
            "Mortgage renewal offer",
            (
                r"\brenewal\s+(?:offer|agreement|interest\s+rate|term)\b",
                r"\bmaturity\s+date\b",
                r"\bremaining\s+amorti[sz]ation\b",
                r"\boffered\s+(?:interest\s+)?rate\b",
            ),
            5,
        ),
        DocumentSignal(
            "payout_statement",
            "Mortgage payout statement",
            (
                r"\bpayout\s+(?:statement|amount|figure)\b",
                r"\bdischarge\s+(?:fee|statement|amount)\b",
                r"\bper\s+diem\b",
                r"\binterest\s+rate\s+differential\b|\bIRD\b",
            ),
            5,
        ),
        DocumentSignal(
            "annual_statement",
            "Mortgage annual statement",
            (
                r"\bannual\s+statement\b",
                r"\bstatement\s+period\b",
                r"\byear\s+end\b",
                r"\binterest\s+paid\b",
            ),
            4,
        ),
        DocumentSignal(
            "rate_quote",
            "Mortgage rate quote",
            (
                r"\brate\s+hold\b",
                r"\bpre[- ]?approval\b",
                r"\bquote\s+expires\b",
                r"\brate\s+guarantee\b",
            ),
            4,
        ),
        DocumentSignal(
            "servicing_notice",
            "Mortgage servicing notice",
            (
                r"\bservicing\b",
                r"\bpayment\s+change\b",
                r"\bescrow\b",
                r"\bproperty\s+tax\b",
            ),
            3,
        ),
    )


def section_specs() -> tuple[SectionSpec, ...]:
    return (
        SectionSpec("summary", "Summary", (r"\bsummary\b", r"\baccount\s+overview\b")),
        SectionSpec("rates", "Rates", (r"\binterest\s+rate\b", r"\brate\s+details\b")),
        SectionSpec("payments", "Payments", (r"\bpayment\s+(?:amount|details|frequency)\b",)),
        SectionSpec("term", "Term", (r"\brenewal\s+term\b", r"\bterm\s+length\b")),
        SectionSpec("amortization", "Amortization", (r"\bamorti[sz]ation\b",)),
        SectionSpec("maturity", "Maturity", (r"\bmaturity\s+date\b", r"\bexpiry\s+date\b")),
        SectionSpec("prepayment", "Prepayment", (r"\bprepayment\b", r"\bprepay\b")),
        SectionSpec("penalty", "Penalty", (r"\bpenalt(?:y|ies)\b", r"\bIRD\b", r"\bdifferential\b")),
        SectionSpec("fees", "Fees", (r"\bfees?\b", r"\bcharges?\b")),
        SectionSpec("insurance", "Insurance", (r"\binsurance\b", r"\bcreditor\s+protection\b")),
        SectionSpec("taxes", "Property taxes", (r"\bproperty\s+tax\b", r"\btaxes\b")),
        SectionSpec("instructions", "Instructions", (r"\bsign\b", r"\breturn\b", r"\bcall\b")),
        SectionSpec("privacy", "Privacy", (r"\bprivacy\b", r"\bpersonal\s+information\b")),
    )


def clause_specs() -> tuple[ClauseSpec, ...]:
    return (
        ClauseSpec(
            "prepayment_privilege",
            "Prepayment privilege",
            (
                r"\bprepayment\s+(?:privilege|option|allowance)\b",
                r"\b(?:10|15|20)%\s+(?:prepayment|lump[- ]sum)\b",
                r"\blump[- ]sum\s+payment\b",
            ),
            "Confirm whether extra principal payments are allowed and whether the amount resets after renewal.",
            risk_if_absent="Prepayment privileges were not visible in the OCR text.",
        ),
        ClauseSpec(
            "interest_rate_differential",
            "Interest rate differential / IRD",
            (
                r"\binterest\s+rate\s+differential\b",
                r"\bIRD\b",
                r"\bgreater\s+of\s+three\s+months\b",
            ),
            "Ask the lender how any fixed-rate break penalty is calculated and which comparison rate is used.",
            risk_if_present="Penalty language may affect switching or refinancing before maturity.",
        ),
        ClauseSpec(
            "contract_rate_language",
            "Contract rate language",
            (
                r"\bcontract\s+(?:interest\s+)?rate\b",
                r"\bregistered\s+(?:interest\s+)?rate\b",
                r"\brate\s+used\s+to\s+calculate\s+interest\b",
            ),
            "Confirm whether this is the legal contract rate, the payment rate, or a renewal offer rate.",
            risk_if_present="Contract-rate wording can matter for payment calculations and penalty formulas.",
        ),
        ClauseSpec(
            "contract_discount_language",
            "Contract discount language",
            (
                r"\bcontract\s+discount\b",
                r"\brate\s+discount\b",
                r"\bdiscount\s+(?:from|off)\s+(?:the\s+)?posted\s+rate\b",
                r"\bposted\s+rate\s+less\b",
            ),
            "Check whether the discount is carried into renewal, used for IRD, or only applied to the original term.",
            risk_if_present="Posted-rate discounts can change IRD calculations and lender-retention negotiations.",
        ),
        ClauseSpec(
            "three_month_interest_penalty",
            "Three-month interest penalty",
            (
                r"\bthree[- ]month\s+interest\b",
                r"\bthree\s+months?\s+interest\b",
                r"\b3\s+months?\s+interest\b",
            ),
            "Confirm whether three-month interest is a minimum, a variable-rate penalty, or one option in a greater-of formula.",
            risk_if_present="Break-cost language needs lender confirmation before relying on savings estimates.",
        ),
        ClauseSpec(
            "automatic_renewal",
            "Automatic renewal",
            (
                r"\bautomatic(?:ally)?\s+renew",
                r"\brenew(?:ed)?\s+automatically\b",
                r"\bif\s+we\s+do\s+not\s+hear\s+from\s+you\b",
            ),
            "Confirm the deadline for declining or changing the renewal offer.",
            risk_if_present="The borrower may be renewed into terms they did not actively choose.",
        ),
        ClauseSpec(
            "rate_hold_or_expiry",
            "Rate hold or offer expiry",
            (
                r"\brate\s+hold\b",
                r"\boffer\s+expires\b",
                r"\bvalid\s+until\b",
                r"\bexpiry\s+date\b",
            ),
            "Record the last date the offer can be accepted and whether the rate can change before then.",
            risk_if_absent="The OCR text did not expose an offer-expiry deadline.",
        ),
        ClauseSpec(
            "mortgage_date_language",
            "Mortgage date or funding date",
            (
                r"\bmortgage\s+date\b",
                r"\bfunding\s+date\b",
                r"\badvance\s+date\b",
                r"\borigination\s+date\b",
                r"\binterest\s+adjustment\s+date\b",
            ),
            "Record the date the mortgage began or funds advanced, because it anchors term, discount and penalty context.",
            risk_if_absent="The OCR text did not expose the mortgage start/origination date.",
        ),
        ClauseSpec(
            "portability",
            "Portability",
            (
                r"\bportable\b",
                r"\bportability\b",
                r"\btransfer\s+your\s+mortgage\b",
            ),
            "Ask whether the mortgage can be ported to a new property and under what conditions.",
        ),
        ClauseSpec(
            "blend_and_extend",
            "Blend and extend",
            (
                r"\bblend\s+and\s+extend\b",
                r"\bblended\s+rate\b",
            ),
            "Confirm how the blended rate was calculated and whether it hides an embedded penalty.",
            risk_if_present="Blended offers can make comparison with clean switch rates harder.",
        ),
        ClauseSpec(
            "collateral_charge",
            "Collateral charge",
            (
                r"\bcollateral\s+charge\b",
                r"\bcollateral\s+mortgage\b",
            ),
            "Confirm registration type and whether legal/discharge costs differ from a standard charge.",
            risk_if_present="Collateral-charge mortgages can affect switching logistics and costs.",
        ),
        ClauseSpec(
            "cashback_or_clawback",
            "Cashback or clawback",
            (
                r"\bcash\s*back\b",
                r"\bcashback\b",
                r"\bclaw\s*back\b",
                r"\brepay\s+the\s+cash\b",
            ),
            "Ask whether incentives must be repaid if the mortgage is discharged early.",
            risk_if_present="Cashback clawbacks can change the economics of switching.",
        ),
        ClauseSpec(
            "insurance_or_protection",
            "Insurance or creditor protection",
            (
                r"\bcreditor\s+insurance\b",
                r"\bmortgage\s+protection\b",
                r"\blife\s+insurance\b",
                r"\bdisability\s+insurance\b",
            ),
            "Separate optional insurance premiums from required mortgage payments.",
            risk_if_present="Insurance premiums can make payment comparisons look higher than principal-and-interest alone.",
        ),
        ClauseSpec(
            "property_tax_collection",
            "Property tax collection",
            (
                r"\bproperty\s+tax(?:es)?\b",
                r"\btax\s+account\b",
                r"\bmunicipal\s+tax\b",
            ),
            "Check whether the lender collects property taxes and whether payments include a tax component.",
            risk_if_present="Payment amount may include taxes, which should not be compared as pure mortgage debt service.",
        ),
    )


def _excerpt(text: str, start: int, end: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return redact_sensitive_text(text[left:right])


def _normalize_money(value: str) -> Decimal | None:
    token = re.sub(r"[^0-9.]", "", value)
    if not token:
        return None
    try:
        amount = Decimal(token).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or amount > Decimal("100000000"):
        return None
    return amount


def _normalize_percent(value: str) -> Decimal | None:
    token = str(value or "").replace("%", "").strip()
    try:
        rate = Decimal(token).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if rate < 0 or rate > Decimal("40"):
        return None
    return rate


def _field_value(extraction: dict, key: str) -> Any:
    payload = extraction.get("fields", {}).get(key)
    if not payload:
        return None
    return payload.get("value")


def classify_document(pages: list[OCRTextPage]) -> dict:
    text = " ".join(flatten_ocr_text(page.text) for page in pages)
    scores = []
    for signal in document_signals():
        matches = []
        for pattern in signal.patterns:
            found = re.findall(pattern, text, flags=re.I)
            if found:
                matches.append({"pattern": pattern, "count": len(found)})
        score = sum(item["count"] for item in matches) * signal.weight
        if score:
            scores.append(
                {
                    "type": signal.key,
                    "label": signal.label,
                    "score": score,
                    "matches": matches,
                }
            )
    scores.sort(key=lambda item: (-item["score"], item["type"]))
    if not scores:
        return {
            "type": "unknown",
            "label": "Unknown mortgage document",
            "confidence": "low",
            "score": 0,
            "signals": [],
        }
    best = scores[0]
    confidence = "high" if best["score"] >= 15 else "medium" if best["score"] >= 8 else "low"
    return {
        "type": best["type"],
        "label": best["label"],
        "confidence": confidence,
        "score": best["score"],
        "signals": scores[:5],
    }


def detect_sections(pages: list[OCRTextPage]) -> list[dict]:
    sections = []
    seen = set()
    for page in pages:
        text = flatten_ocr_text(page.text)
        for spec in section_specs():
            for pattern in spec.patterns:
                match = re.search(pattern, text, flags=re.I)
                if not match:
                    continue
                key = (spec.key, page.page_number)
                if key in seen:
                    continue
                seen.add(key)
                sections.append(
                    {
                        "section": spec.key,
                        "label": spec.label,
                        "page": page.page_number,
                        "confidence": "high" if match.start() < 300 else "medium",
                        "excerpt": _excerpt(text, match.start(), match.end()),
                    }
                )
                break
    return sections[:MAX_SECTIONS]


def _detail_label(context: str, fallback: str) -> str:
    context = redact_sensitive_text(context)
    context = re.sub(r"\s+", " ", context).strip(" :-")
    if not context:
        return fallback
    words = context.split()
    return " ".join(words[-7:])[:80] or fallback


def extract_fine_details(pages: list[OCRTextPage]) -> list[dict]:
    details = []
    patterns = (
        ("money", r"(?:CAD\s*)?\$?\s*\d[\d,\s]{2,}(?:\.\d{1,2})?"),
        ("percent", r"\b\d{1,2}(?:\.\d{1,3})?\s*%"),
        (
            "date",
            r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})\b",
        ),
        ("duration", r"\b\d{1,3}\s*(?:years?|yrs?|months?|mos?|mths?)\b"),
    )
    for page in pages:
        text = flatten_ocr_text(page.text)
        for kind, pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.I):
                if len(details) >= MAX_FINE_DETAILS:
                    return details
                raw = match.group(0)
                context = text[max(0, match.start() - 70):match.start()]
                normalized: Any = raw.strip()
                if kind == "money":
                    amount = _normalize_money(raw)
                    if amount is None:
                        continue
                    normalized = float(amount)
                elif kind == "percent":
                    rate = _normalize_percent(raw)
                    if rate is None:
                        continue
                    normalized = float(rate)
                details.append(
                    {
                        "kind": kind,
                        "label_guess": _detail_label(context, kind),
                        "value": normalized,
                        "raw_display": redact_sensitive_text(raw),
                        "page": page.page_number,
                        "excerpt": _excerpt(text, match.start(), match.end(), radius=80),
                    }
                )
    return details


def detect_clauses(pages: list[OCRTextPage]) -> list[dict]:
    findings = []
    page_text = [(page, flatten_ocr_text(page.text)) for page in pages]
    for spec in clause_specs():
        found = None
        for page, text in page_text:
            for pattern in spec.patterns:
                match = re.search(pattern, text, flags=re.I)
                if match:
                    found = (page, text, match, pattern)
                    break
            if found:
                break
        if found:
            page, text, match, pattern = found
            findings.append(
                {
                    "clause": spec.key,
                    "label": spec.label,
                    "status": "found",
                    "page": page.page_number,
                    "excerpt": _excerpt(text, match.start(), match.end()),
                    "matched_pattern": pattern,
                    "review_prompt": spec.review_prompt,
                    "risk": spec.risk_if_present,
                }
            )
        elif spec.risk_if_absent:
            findings.append(
                {
                    "clause": spec.key,
                    "label": spec.label,
                    "status": "not_found",
                    "page": None,
                    "excerpt": None,
                    "matched_pattern": None,
                    "review_prompt": spec.review_prompt,
                    "risk": spec.risk_if_absent,
                }
            )
    return findings


def _monthly_payment(balance: float, annual_rate: float, months: int) -> float | None:
    if balance <= 0 or annual_rate < 0 or months <= 0:
        return None
    monthly = annual_rate / 100 / 12
    if monthly == 0:
        return round(balance / months, 2)
    payment = balance * monthly / (1 - math.pow(1 + monthly, -months))
    return round(payment, 2)


def consistency_checks(extraction: dict) -> list[dict]:
    checks = []
    fields = extraction.get("fields", {})
    balance = _field_value(extraction, "balance")
    offered_rate = _field_value(extraction, "offered_rate")
    current_rate = _field_value(extraction, "current_rate")
    payment = _field_value(extraction, "payment_amount")
    amortization = _field_value(extraction, "amortization_months")
    term = _field_value(extraction, "term_months")
    maturity = _field_value(extraction, "maturity_date")
    contract_rate = _field_value(extraction, "contract_rate")
    posted_rate = _field_value(extraction, "posted_rate")
    contract_discount = _field_value(extraction, "contract_discount")
    mortgage_start = _field_value(extraction, "mortgage_start_date")
    if balance is not None and offered_rate is not None and amortization:
        estimated = _monthly_payment(float(balance), float(offered_rate), int(amortization))
        if estimated and payment:
            delta = abs(float(payment) - estimated)
            tolerance = max(35.0, estimated * 0.08)
            checks.append(
                {
                    "check": "payment_vs_balance_rate_amortization",
                    "status": "pass" if delta <= tolerance else "review",
                    "expected_monthly_payment_estimate": estimated,
                    "observed_payment": round(float(payment), 2),
                    "delta": round(delta, 2),
                    "detail": "Observed payment is close to a simple monthly estimate"
                    if delta <= tolerance
                    else "Observed payment differs from a simple estimate; payment may include taxes, insurance, different compounding or a non-monthly frequency.",
                }
            )
        else:
            checks.append(
                {
                    "check": "payment_vs_balance_rate_amortization",
                    "status": "not_enough_data",
                    "detail": "Balance, offered rate and amortization were found, but payment amount was not.",
                }
            )
    if current_rate is not None and offered_rate is not None:
        change = round(float(offered_rate) - float(current_rate), 4)
        checks.append(
            {
                "check": "offered_rate_vs_current_rate",
                "status": "review" if abs(change) >= 1.0 else "pass",
                "change_percentage_points": change,
                "detail": "Rate change is one percentage point or more; confirm renewal impact."
                if abs(change) >= 1.0
                else "Rate change is under one percentage point.",
            }
        )
    if contract_rate is not None and posted_rate is not None:
        implied_discount = round(float(posted_rate) - float(contract_rate), 4)
        detail = "Posted rate minus contract rate gives an implied discount."
        status = "pass"
        if implied_discount < -0.05:
            status = "review"
            detail = "Contract rate appears higher than posted rate; verify labels and OCR."
        if contract_discount is not None:
            gap = abs(implied_discount - float(contract_discount))
            status = "pass" if gap <= 0.08 and status == "pass" else "review"
            detail = (
                "Contract discount matches posted rate minus contract rate."
                if gap <= 0.08 and status == "pass"
                else "Contract discount does not line up with posted rate minus contract rate; verify which rate each label refers to."
            )
            checks.append(
                {
                    "check": "contract_rate_discount_math",
                    "status": status,
                    "posted_rate": round(float(posted_rate), 4),
                    "contract_rate": round(float(contract_rate), 4),
                    "contract_discount": round(float(contract_discount), 4),
                    "implied_discount": implied_discount,
                    "delta": round(gap, 4),
                    "detail": detail,
                }
            )
        else:
            checks.append(
                {
                    "check": "contract_rate_discount_math",
                    "status": "review" if implied_discount > 0.05 else status,
                    "posted_rate": round(float(posted_rate), 4),
                    "contract_rate": round(float(contract_rate), 4),
                    "implied_discount": implied_discount,
                    "detail": detail + " Confirm whether the document names this as the contract discount.",
                }
            )
    elif contract_discount is not None and (contract_rate is None or posted_rate is None):
        checks.append(
            {
                "check": "contract_rate_discount_math",
                "status": "review",
                "contract_discount": round(float(contract_discount), 4),
                "detail": "A contract discount was found, but posted rate or contract rate was not found.",
            }
        )
    if term is not None and amortization is not None:
        checks.append(
            {
                "check": "term_not_longer_than_amortization",
                "status": "pass" if int(term) <= int(amortization) else "review",
                "term_months": int(term),
                "amortization_months": int(amortization),
                "detail": "Term is not longer than remaining amortization."
                if int(term) <= int(amortization)
                else "Term appears longer than remaining amortization; verify OCR.",
            }
        )
    if maturity:
        try:
            parsed = date.fromisoformat(str(maturity))
            days_until = (parsed - date.today()).days
            checks.append(
                {
                    "check": "maturity_date_timing",
                    "status": "review" if days_until < 0 else "pass",
                    "days_until_maturity": days_until,
                    "detail": "Maturity date is in the past."
                    if days_until < 0
                    else "Maturity date is not in the past.",
                }
            )
        except ValueError:
            checks.append(
                {
                    "check": "maturity_date_timing",
                    "status": "review",
                    "detail": "Maturity date could not be parsed after extraction.",
                }
            )
    if mortgage_start and maturity:
        try:
            start = date.fromisoformat(str(mortgage_start))
            end = date.fromisoformat(str(maturity))
            months_between = (end.year - start.year) * 12 + (end.month - start.month)
            if end.day < start.day:
                months_between -= 1
            term_gap = abs(months_between - int(term)) if term is not None else None
            checks.append(
                {
                    "check": "mortgage_date_term_maturity_sequence",
                    "status": "pass"
                    if end > start and (term_gap is None or term_gap <= 2)
                    else "review",
                    "mortgage_start_date": str(mortgage_start),
                    "maturity_date": str(maturity),
                    "months_between": months_between,
                    "term_months": int(term) if term is not None else None,
                    "detail": "Mortgage start date, term and maturity are internally plausible."
                    if end > start and (term_gap is None or term_gap <= 2)
                    else "Mortgage date, term and maturity do not line up cleanly; verify the source document dates.",
                }
            )
        except (TypeError, ValueError):
            checks.append(
                {
                    "check": "mortgage_date_term_maturity_sequence",
                    "status": "review",
                    "detail": "Mortgage start or maturity date could not be parsed for timeline checking.",
                }
            )
    missing = [key for key in ("balance", "offered_rate", "amortization_months", "maturity_date") if key not in fields]
    checks.append(
        {
            "check": "required_field_completeness",
            "status": "pass" if not missing else "review",
            "missing": missing,
            "detail": "All required comparison fields were found."
            if not missing
            else "Required fields need manual entry: " + ", ".join(missing),
        }
    )
    return checks


def build_review_questions(extraction: dict, clauses: list[dict], checks: list[dict]) -> list[dict]:
    questions = []
    for item in extraction.get("review_packet", []):
        if item.get("status") in {"missing_required", "needs_review"}:
            questions.append(
                {
                    "topic": item.get("field"),
                    "priority": "high" if item.get("blocking") else "medium",
                    "question": item.get("prompt"),
                    "source": "field_review",
                }
            )
    for clause in clauses:
        if clause.get("risk"):
            questions.append(
                {
                    "topic": clause["clause"],
                    "priority": "medium" if clause["status"] == "found" else "low",
                    "question": clause["review_prompt"],
                    "source": "clause_detection",
                }
            )
    for check in checks:
        if check.get("status") == "review":
            questions.append(
                {
                    "topic": check["check"],
                    "priority": "high",
                    "question": check["detail"],
                    "source": "consistency_check",
                }
            )
    unique = []
    seen = set()
    for question in questions:
        key = (question["topic"], question["question"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(question)
    return unique[:MAX_REVIEW_QUESTIONS]


def understanding_score(extraction: dict, classification: dict, clauses: list[dict],
                        checks: list[dict]) -> dict:
    score = 20
    field_count = len(extraction.get("fields", {}))
    score += min(35, field_count * 5)
    if classification.get("confidence") == "high":
        score += 15
    elif classification.get("confidence") == "medium":
        score += 8
    found_clauses = sum(1 for clause in clauses if clause.get("status") == "found")
    score += min(15, found_clauses * 3)
    review_checks = sum(1 for check in checks if check.get("status") == "review")
    score -= min(25, review_checks * 7)
    if extraction.get("review_status") == "blocked":
        score -= 20
    score = max(0, min(100, score))
    if score >= 75:
        label = "strong"
    elif score >= 50:
        label = "partial"
    else:
        label = "thin"
    return {
        "score": score,
        "label": label,
        "field_count": field_count,
        "found_clause_count": found_clauses,
        "review_check_count": review_checks,
    }


def narrative_summary(extraction: dict, classification: dict, checks: list[dict]) -> list[str]:
    fields = extraction.get("fields", {})
    sentences = [
        f"Document appears to be: {classification.get('label', 'Unknown mortgage document')} ({classification.get('confidence', 'low')} confidence)."
    ]
    if "lender" in fields:
        sentences.append(f"Lender identified as {fields['lender']['display_value']}.")
    if "balance" in fields and "offered_rate" in fields:
        sentences.append(
            "Core renewal numbers found: "
            f"balance {fields['balance']['display_value']} and offered rate {fields['offered_rate']['display_value']}%."
        )
    if "contract_rate" in fields or "contract_discount" in fields:
        contract_bits = []
        if "contract_rate" in fields:
            contract_bits.append(f"contract rate {fields['contract_rate']['display_value']}%")
        if "posted_rate" in fields:
            contract_bits.append(f"posted rate {fields['posted_rate']['display_value']}%")
        if "contract_discount" in fields:
            contract_bits.append(f"contract discount {fields['contract_discount']['display_value']}%")
        sentences.append("Contract-rate details found: " + ", ".join(contract_bits) + ".")
    if "mortgage_start_date" in fields:
        sentences.append(f"Mortgage start/origination date found as {fields['mortgage_start_date']['display_value']}.")
    if "term_months" in fields:
        sentences.append(f"Term length found as {fields['term_months']['display_value']} months.")
    if extraction.get("missing_required"):
        sentences.append("Missing required fields: " + ", ".join(extraction["missing_required"]) + ".")
    review_count = sum(1 for check in checks if check.get("status") == "review")
    if review_count:
        sentences.append(f"{review_count} consistency check(s) need human review.")
    else:
        sentences.append("No deterministic consistency check raised a review flag.")
    return sentences


def understand_ocr_document(pages: list[Any], *, filename: str = "ocr.txt",
                            corrections: dict[str, Any] | None = None,
                            min_confidence: float = 0.0) -> dict:
    prepared = prepare_pages(pages)
    extraction = extract_ocr_fields(
        prepared,
        filename=filename,
        corrections=corrections,
        min_confidence=min_confidence,
    )
    classification = classify_document(prepared)
    sections = detect_sections(prepared)
    fine_details = extract_fine_details(prepared)
    clauses = detect_clauses(prepared)
    checks = consistency_checks(extraction)
    questions = build_review_questions(extraction, clauses, checks)
    score = understanding_score(extraction, classification, clauses, checks)
    return {
        "provider": "deterministic-document-understanding-v11",
        "filename": str(filename or "ocr.txt")[:120],
        "classification": classification,
        "summary": narrative_summary(extraction, classification, checks),
        "canadian_mortgage_terms": explain_extracted_terms(extraction),
        "section_map": sections,
        "fine_details": fine_details,
        "clauses": clauses,
        "consistency_checks": checks,
        "review_questions": questions,
        "understanding_score": score,
        "extraction": extraction,
        "raw_ocr_stored": False,
        "notice": "Document understanding is deterministic assistance, not proof of lender terms.",
    }
