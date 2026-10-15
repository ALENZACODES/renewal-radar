"""Audit mortgage evidence without merging facts from different contract terms."""
from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date
from decimal import Decimal
from typing import Any

from .fields import redact_sensitive_text
from .semantic_evidence_v16 import (
    DocumentSemanticAuditError,
    SCOPES,
    apply_semantic_corrections,
    canonical_text,
    extract_semantic_mentions,
    resolve_semantic_facts,
    validate_pages,
)


SOURCE_LINKS = (
    {
        "id": "fcac-penalties",
        "title": "FCAC: Mortgage prepayment penalties",
        "url": "https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html",
    },
    {
        "id": "fcac-terms",
        "title": "FCAC: Mortgage terms and amortization",
        "url": "https://www.canada.ca/en/financial-consumer-agency/services/mortgages/mortgage-terms-amortization.html",
    },
    {
        "id": "fcac-disclosure",
        "title": "FCAC: Mortgage prepayment penalty disclosure",
        "url": "https://www.canada.ca/en/financial-consumer-agency/services/industry/commissioner-guidance/guidance-9.html",
    },
)
CLAUSE_PATTERNS = {
    "ird": r"\b(?:interest\s+rate\s+differential|IRD)\b",
    "three_month_interest": r"\b(?:three|3)[- ]months?[\s'-]*interest\b",
    "prepayment_penalty": r"\b(?:prepayment\s+(?:penalt(?:y|ies)|charge)|break\s+(?:fee|penalty))\b",
    "discount_for_ird": r"\b(?:original|contract)\s+discount\b|\bposted\s+rate\s+(?:minus|less)\b",
    "automatic_renewal": r"\b(?:automatically\s+renew|automatic\s+renewal|renew(?:s|ed)?\s+automatically)\b",
    "tax_in_payment": r"\b(?:property\s+tax|taxes)\b.*\b(?:included|added|collected)\b",
    "insurance_in_payment": r"\b(?:insurance|protection\s+premium)\b.*\b(?:included|added|collected)\b",
}


def _check(key: str, status: str, title: str, detail: str, evidence: list[str],
           *, scope: str = "document", inputs: dict | None = None,
           output: Any = None, formula: str | None = None) -> dict:
    return {
        "id": f"{scope}:{key}",
        "scope": scope,
        "status": status,
        "title": title,
        "detail": detail,
        "evidence": list(dict.fromkeys(evidence)),
        "inputs": inputs or {},
        "output": output,
        "formula": formula,
    }


def _fact(facts: dict, scope: str, field: str) -> dict:
    return facts.get(f"{scope}.{field}", {})


def _resolved(facts: dict, scope: str, field: str) -> Any:
    fact = _fact(facts, scope, field)
    return fact.get("value") if fact.get("status") == "resolved" else None


def _evidence(facts: dict, scope: str, fields: tuple[str, ...]) -> list[str]:
    return [item for field in fields for item in _fact(facts, scope, field).get("evidence", [])]


def _active_scopes(facts: dict) -> list[str]:
    return [scope for scope in SCOPES if any(fact["scope"] == scope for fact in facts.values())]


def audit_fact_quality(facts: dict) -> list[dict]:
    checks = []
    for key, fact in facts.items():
        status = fact["status"]
        if status == "resolved" and fact["scope"] != "unspecified":
            continue
        if status == "conflict":
            detail = "Different values occur within the same term context. Select the correct source."
            check_status = "conflict"
        elif status == "unreadable":
            detail = "The label was found but its value or OCR confidence cannot support a calculation."
            check_status = "review"
        elif status == "review":
            detail = "OCR character repair changed a numeric token. Confirm it against the document."
            check_status = "review"
        else:
            detail = "Identify whether this value belongs to the original term, renewal, or payout."
            check_status = "review"
        checks.append(_check(
            "fact-" + fact["field"], check_status, key.replace("_", " "), detail,
            fact["evidence"], scope=fact["scope"], output=fact.get("value"),
        ))
    return checks


def audit_rate_relationships(facts: dict) -> list[dict]:
    checks = []
    fields = ("posted_rate", "contract_rate", "contract_discount")
    for scope in _active_scopes(facts):
        if not any(_fact(facts, scope, field) for field in fields):
            continue
        inputs = {field: _resolved(facts, scope, field) for field in fields}
        evidence = _evidence(facts, scope, fields)
        if any(value is None for value in inputs.values()):
            checks.append(_check(
                "rate-discount", "incomplete", "Posted rate and contract discount",
                "All three confirmed rates must belong to the same term to check the discount.",
                evidence, scope=scope, inputs=inputs,
                formula="posted_rate - contract_rate = contract_discount (percentage points)",
            ))
            continue
        posted, contract, discount = (Decimal(str(inputs[field])) for field in fields)
        expected = posted - contract
        residual = expected - discount
        consistent = abs(residual) <= Decimal("0.005") and expected >= 0
        checks.append(_check(
            "rate-discount", "consistent" if consistent else "conflict",
            "Posted rate and contract discount",
            "The stated discount matches the posted-to-contract rate difference."
            if consistent else "The stated discount differs from the posted-to-contract rate difference.",
            evidence, scope=scope, inputs=inputs,
            output={"calculated_discount_points": float(expected), "residual_points": float(residual)},
            formula="posted_rate - contract_rate = contract_discount (percentage points)",
        ))
    original = _resolved(facts, "original", "contract_rate")
    offered = _resolved(facts, "renewal", "offered_rate")
    if original is not None and offered is not None:
        difference = Decimal(str(offered)) - Decimal(str(original))
        checks.append(_check(
            "renewal-rate-change", "observed", "Renewal rate change",
            "This compares two different terms; it is not a contract discount or an IRD comparison rate.",
            _evidence(facts, "original", ("contract_rate",)) + _evidence(facts, "renewal", ("offered_rate",)),
            inputs={"original_contract_rate": original, "renewal_offered_rate": offered},
            output={"change_percentage_points": float(difference), "change_basis_points": float(difference * 100)},
            formula="renewal_offered_rate - original_contract_rate",
        ))
    return checks


def add_calendar_months(start: date, months: int) -> date:
    if isinstance(months, bool) or not isinstance(months, int) or not 0 <= months <= 600:
        raise DocumentSemanticAuditError("Term months must be an integer from 0 to 600")
    total = start.year * 12 + start.month - 1 + months
    year, month_index = divmod(total, 12)
    if not 1 <= year <= 9999:
        raise DocumentSemanticAuditError("Term end falls outside the supported calendar")
    month = month_index + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def audit_term_timelines(facts: dict, as_of: date) -> list[dict]:
    checks = []
    for scope in _active_scopes(facts):
        start_key = "term_start_date"
        if not _fact(facts, scope, start_key) and scope in ("original", "unspecified"):
            start_key = "mortgage_start_date"
        fields = (start_key, "maturity_date", "term_months")
        values = {field: _resolved(facts, scope, field) for field in fields}
        if not any(_fact(facts, scope, field) for field in fields):
            continue
        evidence = _evidence(facts, scope, fields)
        if any(value is None for value in values.values()):
            checks.append(_check(
                "term-calendar", "incomplete", "Term dates",
                "A start date, maturity date, and term length in the same context are required.",
                evidence, scope=scope, inputs=values,
            ))
        else:
            start = date.fromisoformat(values[start_key])
            maturity = date.fromisoformat(values["maturity_date"])
            expected = add_calendar_months(start, values["term_months"])
            delta = (maturity - expected).days
            checks.append(_check(
                "term-calendar", "consistent" if delta == 0 else "conflict",
                "Term dates", "The stated maturity matches the term's calendar end."
                if delta == 0 else "The dates do not match the stated term. Confirm adjustment dates or amendments.",
                evidence, scope=scope, inputs=values,
                output={"expected_maturity": expected.isoformat(), "difference_days": delta},
                formula="calendar_add_months(term_start_date, term_months)",
            ))
        maturity_value = _resolved(facts, scope, "maturity_date")
        if maturity_value:
            days = (date.fromisoformat(maturity_value) - as_of).days
            checks.append(_check(
                "maturity-distance", "observed", "Time until maturity",
                "Calendar days are measured from the requested audit date; a lender determines penalty day-count rules.",
                _evidence(facts, scope, ("maturity_date",)), scope=scope,
                inputs={"as_of": as_of.isoformat(), "maturity_date": maturity_value},
                output={"days_remaining": days, "has_matured": days < 0},
            ))
        amortization = _resolved(facts, scope, "amortization_months")
        term = values["term_months"]
        if amortization is not None and term is not None:
            checks.append(_check(
                "term-amortization", "consistent" if term <= amortization else "review",
                "Term and amortization",
                "The amortization is the repayment horizon; the term is the duration of this contract."
                if term <= amortization else "The term exceeds remaining amortization. Confirm the repayment plan.",
                _evidence(facts, scope, ("amortization_months", "term_months")), scope=scope,
                inputs={"term_months": term, "amortization_months": amortization},
                output={"months_after_term": amortization - term},
            ))
    expiry = _resolved(facts, "renewal", "offer_expiry_date")
    start = _resolved(facts, "renewal", "term_start_date")
    if expiry and start:
        gap = (date.fromisoformat(start) - date.fromisoformat(expiry)).days
        checks.append(_check(
            "offer-window", "observed", "Offer expiry and term start",
            "An acceptance deadline is distinct from the mortgage maturity date.",
            _evidence(facts, "renewal", ("offer_expiry_date", "term_start_date")), scope="renewal",
            inputs={"offer_expiry_date": expiry, "term_start_date": start},
            output={"days_between_expiry_and_start": gap},
        ))
    return checks


def _clause_assertion(segment: str, match: re.Match) -> str:
    prefix = segment[max(0, match.start() - 70):match.start()]
    suffix = segment[match.end():match.end() + 70]
    negative = (re.search(r"\b(?:no|without)\s+(?:a\s+)?$", prefix, re.I)
                or re.match(r"\s+(?:does\s+not|will\s+not|is\s+not)\s+(?:apply|charged|payable|required)", suffix, re.I))
    conditional = re.search(r"\b(?:if|unless|subject\s+to|provided\s+that|except)\b", segment, re.I)
    if conditional:
        return "conditional"
    if negative:
        return "negated"
    if re.search(r"\b(?:example|illustrat(?:ion|ive)|hypothetical)\b", segment, re.I):
        return "example"
    return "mentioned"


def extract_semantic_clauses(prepared: list) -> list[dict]:
    clauses = []
    for page in prepared:
        for line_number, raw in enumerate(page.text.splitlines(), 1):
            text = canonical_text(raw)
            # Clause-local polarity avoids negating another sentence on the line.
            for segment in re.split(r"(?<=[.!?;])\s+", text):
                for topic, pattern in CLAUSE_PATTERNS.items():
                    for match in re.finditer(pattern, segment, re.I):
                        material = f"{page.page_number}|{line_number}|{topic}|{segment}|{match.start()}"
                        clauses.append({
                            "id": "clause-" + hashlib.sha256(material.encode()).hexdigest()[:16],
                            "topic": topic,
                            "assertion": _clause_assertion(segment, match),
                            "page": page.page_number,
                            "line": line_number,
                            "excerpt": redact_sensitive_text(segment)[:300],
                            "source_hash": page.source_hash,
                        })
                        if len(clauses) > 400:
                            raise DocumentSemanticAuditError("Too many mortgage clause mentions")
    return clauses


def audit_penalty_language(clauses: list[dict], facts: dict) -> list[dict]:
    checks = []
    ird = [clause for clause in clauses if clause["topic"] == "ird"]
    evidence = [clause["id"] for clause in ird]
    assertions = {clause["assertion"] for clause in ird}
    if "negated" in assertions and "mentioned" in assertions:
        status = "conflict"
        detail = "IRD wording is both mentioned and negated. Confirm which clause and conditions govern."
    elif assertions and assertions <= {"negated"}:
        status = "observed"
        detail = "The text negates IRD; this does not establish that all discharge fees are waived."
    elif assertions and assertions <= {"example"}:
        status = "review"
        detail = "IRD appears only in illustrative wording. Locate the operative penalty clause."
    elif ird:
        status = "review"
        detail = "Confirm the lender's comparison rate, term mapping, original discount, and payout date."
    else:
        status = "incomplete"
        detail = "No IRD wording was found; missing text does not establish that no penalty applies."
    checks.append(_check("ird-language", status, "Interest rate differential", detail, evidence))
    if ird and any(clause["assertion"] in ("mentioned", "conditional") for clause in ird):
        required = (
            ("original", "contract_rate"), ("original", "contract_discount"),
            ("payout", "comparison_rate"), ("payout", "payout_date"),
        )
        missing = [f"{scope}.{field}" for scope, field in required if _resolved(facts, scope, field) is None]
        checks.append(_check(
            "ird-inputs", "incomplete" if missing else "review", "IRD calculation inputs",
            "A renewal offer is not automatically the lender's IRD comparison rate. The written payout formula controls.",
            evidence + [item for scope, field in required for item in _evidence(facts, scope, (field,))],
            output={"missing_fields": missing, "lender_formula_required": True},
        ))
    for topic in ("three_month_interest", "automatic_renewal", "tax_in_payment", "insurance_in_payment"):
        matches = [clause for clause in clauses if clause["topic"] == topic]
        if matches:
            detail = {
                "three_month_interest": "Confirm whether three-month interest is one branch of a greater-of calculation.",
                "automatic_renewal": "Confirm the opt-out deadline and the terms used for automatic renewal.",
                "tax_in_payment": "A payment including property tax cannot be compared directly with principal and interest alone.",
                "insurance_in_payment": "Separate insurance premiums from principal and interest before comparing payments.",
            }[topic]
            checks.append(_check(topic, "review", topic.replace("_", " ").capitalize(), detail,
                                 [clause["id"] for clause in matches]))
    return checks


def reviewer_prompt_pack(checks: list[dict], mentions: list, clauses: list[dict]) -> list[dict]:
    evidence = {item.id: item.public() for item in mentions}
    evidence.update({item["id"]: item for item in clauses})
    priorities = {"conflict": 0, "review": 1, "incomplete": 2}
    prompts = []
    for check in sorted(checks, key=lambda item: (priorities.get(item["status"], 3), item["id"])):
        if check["status"] not in priorities:
            continue
        refs = [evidence[key] for key in check["evidence"] if key in evidence]
        prompts.append({
            "id": "review-" + check["id"],
            "priority": "high" if check["status"] == "conflict" else "normal",
            "check_id": check["id"],
            "question": check["detail"],
            "scope": check["scope"],
            "pages": sorted({item["page"] for item in refs if item.get("page") is not None}),
            "evidence": check["evidence"],
            "suggested_action": "confirm_source" if refs else "request_missing_document",
        })
    return prompts


def create_document_semantic_audit(pages: list[Any], *, filename: str = "ocr.txt",
                                   corrections: dict | None = None,
                                   min_confidence: float = 0.0,
                                   as_of: date | None = None) -> dict:
    prepared = validate_pages(pages)
    if as_of is not None and (not isinstance(as_of, date) or hasattr(as_of, "hour")):
        raise DocumentSemanticAuditError("Audit date must be a calendar date")
    as_of = as_of or date.today()
    mentions = apply_semantic_corrections(extract_semantic_mentions(prepared), corrections)
    facts = resolve_semantic_facts(mentions, min_confidence)
    clauses = extract_semantic_clauses(prepared)
    checks = (audit_fact_quality(facts) + audit_rate_relationships(facts)
              + audit_term_timelines(facts, as_of) + audit_penalty_language(clauses, facts))
    prompts = reviewer_prompt_pack(checks, mentions, clauses)
    counts = {status: sum(check["status"] == status for check in checks)
              for status in ("consistent", "conflict", "review", "incomplete", "observed")}
    return {
        "provider": "mortgage-document-semantic-auditor-v16",
        "filename": str(filename or "ocr.txt").replace("\\", "/").split("/")[-1][:120],
        "as_of": as_of.isoformat(),
        "pages": [page.public() for page in prepared],
        "mentions": [mention.public() for mention in mentions],
        "facts": facts,
        "clauses": clauses,
        "checks": checks,
        "review_prompts": prompts,
        "summary": {
            "mention_count": len(mentions), "fact_count": len(facts),
            "clause_count": len(clauses), "check_counts": counts,
            "scopes": _active_scopes(facts),
            "status": "conflict" if counts["conflict"] else "review_required" if prompts else "observations_only",
        },
        "sources": [dict(source) for source in SOURCE_LINKS],
        "raw_ocr_stored": False,
        "notice": "Evidence checks support document review. Confirm contract terms and payout amounts with the lender.",
    }
