"""Source-linked mortgage facts with explicit term context and conservative dates."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any

from .fields import (
    OCRFieldError,
    OCRTextPage,
    parse_money,
    parse_percent,
    prepare_pages,
    redact_sensitive_text,
)


class DocumentSemanticAuditError(ValueError):
    """A semantic audit input or correction is invalid."""


SCOPES = ("original", "renewal", "payout", "unspecified")
MAX_MENTIONS = 400
MAX_LINES = 1200
NUMBER = r"[0-9OIl]+(?:[.,][0-9OIl]+)*"
DATE_TOKEN = (
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}/\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
)
SEPARATOR = r"\s*(?:[:=|]|\s[-]\s)?\s*"


@dataclass(frozen=True)
class SemanticRule:
    field: str
    kind: str
    labels: str
    default_scope: str = "unspecified"

    def pattern(self) -> re.Pattern:
        tokens = {
            "rate": rf"(?P<value>{NUMBER})\s*(?P<unit>%|percent\b|percentage\s+points\b|bps\b|basis\s+points\b)",
            "money": r"(?:CAD\s*)?\$?\s*(?P<value>[0-9OIl]+(?:[., ][0-9OIl]+)*)(?![0-9OIl.,])",
            "duration": rf"(?P<value>\d{{1,3}})\s*(?P<unit>months?|mos?|years?|yrs?)\b(?:\s*(?P<extra>\d{{1,2}})\s*months?\b)?",
            "date": rf"(?P<value>{DATE_TOKEN})",
            "frequency": r"(?P<value>accelerated[- ]bi[- ]?weekly|accelerated[- ]weekly|semi[- ]monthly|bi[- ]?weekly|monthly|weekly)\b",
        }
        return re.compile(rf"\b(?:{self.labels}){SEPARATOR}{tokens[self.kind]}", re.I)


RULES = (
    SemanticRule("contract_rate", "rate", r"(?:contract|contractual|registered)\s+(?:interest\s+)?rate"),
    SemanticRule("posted_rate", "rate", r"(?:original\s+)?posted\s+(?:interest\s+)?rate"),
    SemanticRule("comparison_rate", "rate", r"(?:current\s+)?(?:comparison|reference)\s+(?:interest\s+)?rate", "payout"),
    SemanticRule("contract_discount", "rate", r"(?:original\s+)?(?:contract|rate)\s+discount|discount\s+(?:from|off)\s+(?:the\s+)?posted\s+rate"),
    SemanticRule("offered_rate", "rate", r"(?:renewal|offered|new)\s+(?:interest\s+)?rate|renewal\s+offer", "renewal"),
    SemanticRule("current_rate", "rate", r"(?:current|existing)\s+(?:interest\s+)?rate", "original"),
    SemanticRule("balance", "money", r"(?:outstanding\s+)?(?:mortgage\s+)?(?:principal\s+)?balance(?:\s+at\s+renewal)?"),
    SemanticRule("payment_amount", "money", r"(?:regular|monthly|new)?\s*payment(?:\s+amount)?"),
    SemanticRule("term_months", "duration", r"(?:original|renewal|new|existing)?\s*term"),
    SemanticRule("amortization_months", "duration", r"(?:remaining\s+)?amorti[sz]ation(?:\s+period)?"),
    SemanticRule("mortgage_start_date", "date", r"mortgage\s+(?:start\s+)?date|(?:funding|advance|origination)\s+date", "original"),
    SemanticRule("term_start_date", "date", r"(?:original|renewal|new)?\s*(?:term\s+start|effective)\s+date"),
    SemanticRule("renewal_date", "date", r"renewal\s+date", "renewal"),
    SemanticRule("maturity_date", "date", r"(?:original|renewal|new)?\s*maturity\s+date"),
    SemanticRule("offer_expiry_date", "date", r"offer\s+(?:expiry\s+date|expires)|valid\s+until", "renewal"),
    SemanticRule("payout_date", "date", r"payout\s+date|discharge\s+date", "payout"),
    SemanticRule("frequency", "frequency", r"(?:payment\s+)?frequency|payments"),
)
RULE_MAP = {rule.field: rule for rule in RULES}


@dataclass(frozen=True)
class SemanticMention:
    id: str
    field: str
    scope: str
    value: Any
    raw_value: str
    unit: str | None
    page: int | None
    line: int | None
    excerpt: str
    confidence: float | None
    source_hash: str | None
    source: str = "ocr"
    warnings: tuple[str, ...] = ()

    def public(self) -> dict:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


def canonical_text(text: str) -> str:
    text = text.translate(str.maketrans({
        "\u00a0": " ", "\u2013": "-", "\u2014": "-", "\u2212": "-",
        "\ufb01": "fi", "\ufb02": "fl",
    }))
    text = re.sub(r"\bintrest\b", "interest", text, flags=re.I)
    text = re.sub(r"\bdifferental\b", "differential", text, flags=re.I)
    text = re.sub(r"\bdif{1,2}erencial\b", "differential", text, flags=re.I)
    return re.sub(r"[ \t]+", " ", text).strip()


def validate_pages(pages: list[Any]) -> list[OCRTextPage]:
    if not isinstance(pages, list) or not pages:
        raise DocumentSemanticAuditError("Supply at least one OCR text page")
    for item in pages:
        if isinstance(item, dict):
            if not isinstance(item.get("text"), str):
                raise DocumentSemanticAuditError("Page text must be a string")
            number = item.get("page_number", item.get("page"))
            if number is not None and (isinstance(number, bool) or not isinstance(number, int)):
                raise DocumentSemanticAuditError("Page number must be an integer")
        elif not isinstance(item, (str, OCRTextPage)):
            raise DocumentSemanticAuditError("Each page must contain OCR text")
    try:
        prepared = prepare_pages(pages)
    except (OCRFieldError, ValueError, TypeError, OverflowError) as exc:
        raise DocumentSemanticAuditError(str(exc)) from exc
    seen = set()
    for page in prepared:
        if page.page_number in seen:
            raise DocumentSemanticAuditError("Duplicate page numbers are ambiguous")
        seen.add(page.page_number)
        if not isinstance(page.text, str) or len(page.text) > 25000:
            raise DocumentSemanticAuditError("Page text exceeds the text limit")
        if len(page.text.splitlines()) > MAX_LINES:
            raise DocumentSemanticAuditError("Page contains too many lines")
        confidence = page.mean_confidence
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise DocumentSemanticAuditError("Confidence must be finite and between 0 and 1")
    if not any(page.text.strip() for page in prepared):
        raise DocumentSemanticAuditError("Pages contain no readable text")
    return sorted(prepared, key=lambda page: page.page_number)


def parse_semantic_date(raw: str) -> tuple[str | None, tuple[str, ...]]:
    token = raw.strip()
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", token):
        year, month, day = map(int, re.split(r"[-/]", token))
        try:
            return date(year, month, day).isoformat(), ()
        except ValueError:
            return None, ("invalid_date",)
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", token):
        first, second, year = map(int, token.split("/"))
        if first <= 12 and second <= 12 and first != second:
            return None, ("ambiguous_date_order",)
        month, day = (second, first) if first > 12 else (first, second)
        try:
            return date(year, month, day).isoformat(), ()
        except ValueError:
            return None, ("invalid_date",)
    for pattern in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(token, pattern).date().isoformat(), ()
        except ValueError:
            continue
    return None, ("invalid_date",)


def parse_semantic_value(rule: SemanticRule, match: re.Match) -> tuple[Any, tuple[str, ...]]:
    raw = match.group("value")
    if rule.kind == "date":
        return parse_semantic_date(raw)
    if rule.kind == "frequency":
        value = raw.lower().replace("bi-weekly", "biweekly").replace("bi weekly", "biweekly")
        return value.replace("accelerated ", "accelerated-").replace("semi monthly", "semi-monthly"), ()
    if rule.kind == "duration":
        value = int(raw)
        years = match.group("unit").lower().startswith(("year", "yr"))
        extra = int(match.group("extra") or "0")
        if extra and (not years or extra > 11):
            return None, ("invalid_duration",)
        months = value * 12 + extra if years else value
        if not 1 <= months <= 600:
            return None, ("invalid_duration",)
        return months, ()
    if rule.kind == "money":
        digits = raw.translate(str.maketrans({"O": "0", "I": "1", "l": "1"}))
        valid = re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?: \d{3})+)(?:\.\d{1,2})?", digits)
        if not valid:
            return None, ("ambiguous_money_separator",)
        parsed = parse_money(raw)
    else:
        unit = match.group("unit").lower()
        if unit in ("bps", "basis points"):
            try:
                basis_points = float(raw.replace(",", ""))
            except ValueError:
                return None, ("invalid_rate",)
            parsed = parse_percent(str(basis_points / 100))
        else:
            if "," in raw:
                return None, ("ambiguous_decimal_separator",)
            if not re.fullmatch(r"[0-9OIl]+(?:\.[0-9OIl]+)?", raw):
                return None, ("invalid_decimal_separator",)
            parsed = parse_percent(raw)
    if parsed is None:
        return None, (f"invalid_{rule.kind}",)
    warnings = ("ocr_numeric_repair",) if re.search(r"[OIl]", raw) else ()
    return parsed.value, warnings


def scope_in_text(text: str) -> str | None:
    patterns = (
        ("original", r"\b(?:original|existing|current)\s+(?:mortgage|contract|term|rate|posted|discount|maturity|effective)\b"),
        ("renewal", r"\b(?:renewal|new|offered)\s+(?:mortgage|contract|term|rate|posted|maturity|effective|offer)\b"),
        ("payout", r"\b(?:payout|discharge)\s+(?:statement|date|amount|calculation)\b"),
    )
    hits = [scope for scope, pattern in patterns if re.search(pattern, text, re.I)]
    return hits[0] if len(hits) == 1 else None


def heading_scope(text: str) -> str | None:
    if re.search(r"\d|%|\$", text) or len(text) > 100:
        return None
    return scope_in_text(text)


def _mention_id(page: int | None, line: int | None, field: str, scope: str, raw: str) -> str:
    material = f"{page}|{line}|{field}|{scope}|{raw}".encode("utf-8")
    return "mention-" + hashlib.sha256(material).hexdigest()[:16]


def extract_semantic_mentions(prepared: list[OCRTextPage]) -> list[SemanticMention]:
    mentions = []
    for page in prepared:
        # Context resets at every page; a heading on a prior page is not evidence.
        active_scope = "unspecified"
        lines = page.text.splitlines()
        for index, raw_line in enumerate(lines):
            text = canonical_text(raw_line)
            heading = heading_scope(text)
            if heading:
                active_scope = heading
            for rule in RULES:
                matches = list(rule.pattern().finditer(text))
                joined = False
                if not matches and index + 1 < len(lines):
                    # Only a complete label may borrow a value from the next line.
                    label = re.fullmatch(rf"\s*(?:{rule.labels})\s*[:=|]?\s*", text, re.I)
                    if label:
                        text_pair = text + " " + canonical_text(lines[index + 1])
                        matches = list(rule.pattern().finditer(text_pair))
                        joined = True
                for match in matches:
                    value, warnings = parse_semantic_value(rule, match)
                    prefix = text[max(0, match.start() - 30):match.start()]
                    scope = scope_in_text(prefix + match.group(0))
                    if scope is None:
                        scope = rule.default_scope if rule.default_scope != "unspecified" else active_scope
                    raw_value = match.group("value")
                    excerpt = raw_line if not joined else raw_line + " " + lines[index + 1]
                    mention = SemanticMention(
                        id=_mention_id(page.page_number, index + 1, rule.field, scope, raw_value),
                        field=rule.field,
                        scope=scope,
                        value=value,
                        raw_value=raw_value,
                        unit=match.groupdict().get("unit"),
                        page=page.page_number,
                        line=index + 1,
                        excerpt=redact_sensitive_text(excerpt)[:300],
                        confidence=page.mean_confidence,
                        source_hash=page.source_hash,
                        warnings=warnings,
                    )
                    mentions.append(mention)
                    if len(mentions) > MAX_MENTIONS:
                        raise DocumentSemanticAuditError("Too many mortgage field mentions")
    # Exact same evidence can match only once in the returned ledger.
    return list({mention.id: mention for mention in mentions}.values())


def apply_semantic_corrections(mentions: list[SemanticMention], corrections: dict | None) -> list[SemanticMention]:
    if corrections is None:
        return list(mentions)
    if not isinstance(corrections, dict) or len(corrections) > 20:
        raise DocumentSemanticAuditError("Supply at most 20 scoped corrections")
    result = list(mentions)
    for key, value in corrections.items():
        parts = key.split(".") if isinstance(key, str) else []
        if len(parts) != 2 or parts[0] not in SCOPES or parts[1] not in RULE_MAP:
            raise DocumentSemanticAuditError("Corrections must use scope.field keys")
        scope, field = parts
        rule = RULE_MAP[field]
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise DocumentSemanticAuditError("Correction values must be text or numbers")
        raw = str(value).strip()
        if len(raw) > 100:
            raise DocumentSemanticAuditError("Correction is too long")
        suffix = {"rate": "%", "duration": " months"}.get(rule.kind, "")
        label = {
            "contract_rate": "Contract rate", "posted_rate": "Posted rate",
            "comparison_rate": "Comparison rate", "contract_discount": "Contract discount",
            "offered_rate": "Offered rate", "current_rate": "Current rate",
            "balance": "Balance", "payment_amount": "Payment amount",
            "term_months": "Term", "amortization_months": "Amortization",
            "mortgage_start_date": "Mortgage date", "term_start_date": "Term start date",
            "renewal_date": "Renewal date",
            "maturity_date": "Maturity date", "offer_expiry_date": "Offer expires",
            "payout_date": "Payout date", "frequency": "Frequency",
        }[field]
        text = label + ": " + raw + suffix
        match = rule.pattern().fullmatch(text)
        if match is None:
            raise DocumentSemanticAuditError(f"Invalid correction for {key}")
        parsed, warnings = parse_semantic_value(rule, match)
        if parsed is None or warnings:
            raise DocumentSemanticAuditError(f"Correction for {key} needs an unambiguous value")
        result = [replace(item, warnings=item.warnings + ("superseded_by_reviewer",))
                  if item.scope == scope and item.field == field else item for item in result]
        result.append(SemanticMention(
            _mention_id(None, None, field, scope, raw), field, scope, parsed,
            raw, match.groupdict().get("unit"), None, None,
            "Reviewer supplied a correction", 1.0, None, "reviewer",
        ))
    return result


def resolve_semantic_facts(mentions: list[SemanticMention], min_confidence: float = 0.0) -> dict:
    if (isinstance(min_confidence, bool) or not isinstance(min_confidence, (float, int))
            or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1):
        raise DocumentSemanticAuditError("Minimum confidence must be between 0 and 1")
    grouped = {}
    for mention in mentions:
        grouped.setdefault(f"{mention.scope}.{mention.field}", []).append(mention)
    facts = {}
    for key, candidates in sorted(grouped.items()):
        eligible = [item for item in candidates if item.value is not None
                    and "superseded_by_reviewer" not in item.warnings
                    and (item.source == "reviewer" or min_confidence == 0
                         or item.confidence is not None and item.confidence >= min_confidence)]
        values = {str(item.value) for item in eligible}
        status = "resolved" if len(values) == 1 else "conflict" if values else "unreadable"
        if status == "resolved" and any(item.warnings for item in eligible):
            status = "review"
        facts[key] = {
            "field": candidates[0].field,
            "scope": candidates[0].scope,
            "status": status,
            "value": eligible[0].value if len(values) == 1 else None,
            "candidate_values": sorted(values),
            "evidence": [item.id for item in candidates],
            "eligible_evidence": [item.id for item in eligible],
            "source": "reviewer" if any(item.source == "reviewer" for item in eligible) else "ocr",
        }
    return facts
