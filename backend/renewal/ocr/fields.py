"""V10 OCR-to-field workflow for mortgage renewal documents.

This layer consumes OCR text that was already produced by a local engine. It
does not store page text or image bytes. Its job is to produce bounded,
source-linked field candidates, highlight conflicts, and make manual review a
first-class part of the workflow instead of pretending OCR is authoritative.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
from typing import Any

MAX_PAGES = 16
MAX_PAGE_TEXT = 25_000
MAX_CORRECTIONS = 20
MONEY = Decimal("0.01")
REQUIRED_FIELDS = ("balance", "offered_rate", "amortization_months", "maturity_date")


class OCRFieldError(ValueError):
    """The OCR review payload is structurally invalid or unsafe to process."""


@dataclass(frozen=True)
class OCRTextPage:
    page_number: int
    text: str
    mean_confidence: float | None = None
    source_hash: str | None = None

    def public(self) -> dict:
        return {
            "page_number": self.page_number,
            "text_sha256": self.source_hash or text_hash(self.text),
            "text_length": len(self.text),
            "mean_confidence": self.mean_confidence,
        }


@dataclass(frozen=True)
class PatternSpec:
    expression: str
    value_group: int = 1
    confidence: float = 0.72
    name: str = "pattern"
    flags: int = re.I


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    prompt: str
    patterns: tuple[PatternSpec, ...]
    required: bool = False
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedValue:
    value: Any
    display: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldCandidate:
    key: str
    label: str
    value: Any
    display_value: str
    page: int
    excerpt: str
    confidence: str
    confidence_score: float
    source: str
    pattern: str
    warnings: tuple[str, ...] = ()

    def public(self) -> dict:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


def field_specs() -> dict[str, FieldSpec]:
    """Return immutable-ish extraction specs keyed by API field name."""
    return {
        "balance": FieldSpec(
            key="balance",
            label="Mortgage balance",
            kind="money",
            required=True,
            prompt="Confirm the outstanding mortgage balance at renewal.",
            patterns=(
                PatternSpec(
                    r"(?:outstanding\s+)?(?:mortgage\s+)?(?:principal\s+)?balance(?:\s+at\s+renewal)?\s*[:$]?\s*(?:cad\s*)?\$?\s*([0-9OIlS,\s]+(?:[.,]\d{1,2})?)",
                    confidence=0.88,
                    name="balance_label",
                ),
                PatternSpec(
                    r"(?:amount\s+owing|principal\s+amount|renewal\s+balance)\s*:?\s*(?:cad\s*)?\$?\s*([0-9OIlS,\s]+(?:[.,]\d{1,2})?)",
                    confidence=0.82,
                    name="amount_owing",
                ),
            ),
        ),
        "offered_rate": FieldSpec(
            key="offered_rate",
            label="Renewal offered rate",
            kind="percent",
            required=True,
            prompt="Confirm the new renewal interest rate offered by the lender.",
            patterns=(
                PatternSpec(
                    r"(?:renewal\s+offer|renewal\s+(?:interest\s+)?rate|offered\s+(?:interest\s+)?rate|new\s+interest\s+rate)\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.9,
                    name="renewal_rate_label",
                ),
                PatternSpec(
                    r"(?:interest\s+rate)\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.62,
                    name="generic_interest_rate",
                ),
            ),
        ),
        "current_rate": FieldSpec(
            key="current_rate",
            label="Current rate",
            kind="percent",
            prompt="Confirm the rate on the mortgage before renewal.",
            patterns=(
                PatternSpec(
                    r"(?:current|existing|old)\s+(?:interest\s+)?rate\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.86,
                    name="current_rate_label",
                ),
            ),
        ),
        "contract_rate": FieldSpec(
            key="contract_rate",
            label="Contract rate",
            kind="percent",
            prompt="Confirm the contract interest rate used in the mortgage agreement.",
            patterns=(
                PatternSpec(
                    r"(?:contract|registered|mortgage)\s+(?:interest\s+)?rate\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.88,
                    name="contract_rate_label",
                ),
                PatternSpec(
                    r"(?:annual\s+interest\s+rate|rate\s+used\s+to\s+calculate\s+interest)\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.74,
                    name="annual_interest_rate_contract_context",
                ),
            ),
        ),
        "posted_rate": FieldSpec(
            key="posted_rate",
            label="Posted comparison rate",
            kind="percent",
            prompt="Confirm the posted or comparison rate used for discount or penalty calculations.",
            patterns=(
                PatternSpec(
                    r"(?:posted|comparison|reference|benchmark)\s+(?:interest\s+)?rate\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.86,
                    name="posted_rate_label",
                ),
                PatternSpec(
                    r"(?:rate\s+posted\s+by\s+the\s+lender)\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.8,
                    name="posted_rate_sentence",
                ),
            ),
        ),
        "contract_discount": FieldSpec(
            key="contract_discount",
            label="Contract discount",
            kind="percent",
            prompt="Confirm the discount from posted rate that applies to the contract rate.",
            patterns=(
                PatternSpec(
                    r"(?:contract|rate|mortgage)\s+discount\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.87,
                    name="contract_discount_label",
                ),
                PatternSpec(
                    r"discount\s+(?:from|off)\s+(?:the\s+)?posted\s+rate\s*:?\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.88,
                    name="discount_from_posted",
                ),
                PatternSpec(
                    r"posted\s+rate\s+less\s+(?:a\s+)?discount\s+of\s*([0-9OIl.]{1,8})\s*%",
                    confidence=0.84,
                    name="posted_less_discount",
                ),
            ),
        ),
        "payment_amount": FieldSpec(
            key="payment_amount",
            label="Regular payment",
            kind="money",
            prompt="Confirm the regular payment amount and its frequency.",
            patterns=(
                PatternSpec(
                    r"(?:regular|estimated|new|monthly|current)?\s*payment(?:\s+amount)?\s*:?\s*(?:cad\s*)?\$?\s*([0-9OIlS,\s]+(?:[.,]\d{1,2})?)",
                    confidence=0.77,
                    name="payment_amount",
                ),
            ),
        ),
        "term_months": FieldSpec(
            key="term_months",
            label="Renewal term",
            kind="months",
            prompt="Confirm the renewal term length.",
            patterns=(
                PatternSpec(
                    r"(?:renewal\s+)?term\s*:?\s*([0-9OIl]{1,3})\s*(?:months?|mos?|mths?)",
                    confidence=0.84,
                    name="term_months",
                ),
                PatternSpec(
                    r"(?:renewal\s+)?term\s*:?\s*([0-9OIl]{1,2})\s*(?:years?|yrs?)",
                    confidence=0.84,
                    name="term_years",
                ),
            ),
        ),
        "amortization_months": FieldSpec(
            key="amortization_months",
            label="Remaining amortization",
            kind="amortization",
            required=True,
            prompt="Confirm the remaining amortization period.",
            patterns=(
                PatternSpec(
                    r"(?:remaining\s+)?amorti[sz]ation(?:\s+period)?\s*:?\s*([0-9OIl]{1,2})\s*(?:years?|yrs?)(?:\s*([0-9OIl]{1,2})\s*(?:months?|mos?|mths?))?",
                    confidence=0.88,
                    name="amortization_years_months",
                ),
                PatternSpec(
                    r"(?:remaining\s+)?amorti[sz]ation(?:\s+period)?\s*:?\s*([0-9OIl]{1,3})\s*(?:months?|mos?|mths?)",
                    confidence=0.78,
                    name="amortization_months",
                ),
            ),
        ),
        "maturity_date": FieldSpec(
            key="maturity_date",
            label="Maturity date",
            kind="date",
            required=True,
            prompt="Confirm the maturity or renewal date.",
            patterns=(
                PatternSpec(
                    r"(?:maturity|renewal|expiry|expiration)\s+date\s*:?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                    confidence=0.88,
                    name="maturity_date_label",
                ),
            ),
        ),
        "mortgage_start_date": FieldSpec(
            key="mortgage_start_date",
            label="Mortgage start date",
            kind="date",
            prompt="Confirm the mortgage, funding, advance, registration or origination date.",
            patterns=(
                PatternSpec(
                    r"(?:mortgage|loan|term|contract)\s+(?:start\s+)?date\s*:?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                    confidence=0.84,
                    name="mortgage_date_label",
                ),
                PatternSpec(
                    r"(?:funding|advance|origination|registration|interest\s+adjustment)\s+date\s*:?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                    confidence=0.86,
                    name="funding_origination_date",
                ),
            ),
        ),
        "frequency": FieldSpec(
            key="frequency",
            label="Payment frequency",
            kind="enum",
            prompt="Confirm how often payments are made.",
            allowed_values=(
                "monthly",
                "semi-monthly",
                "biweekly",
                "weekly",
                "accelerated-biweekly",
                "accelerated-weekly",
            ),
            patterns=(
                PatternSpec(
                    r"(?:payment\s+)?frequency\s*:?\s*(accelerated\s+bi[- ]?weekly|accelerated\s+weekly|semi[- ]?monthly|bi[- ]?weekly|monthly|weekly)",
                    confidence=0.86,
                    name="frequency_label",
                ),
                PatternSpec(
                    r"payments?\s+(monthly|semi[- ]?monthly|bi[- ]?weekly|weekly)",
                    confidence=0.68,
                    name="frequency_sentence",
                ),
            ),
        ),
        "lender": FieldSpec(
            key="lender",
            label="Lender",
            kind="text",
            prompt="Confirm the lender name shown on the renewal letter.",
            patterns=(
                PatternSpec(
                    r"(?:lender|financial\s+institution|mortgage\s+provider)\s*:?\s*([A-Za-z0-9&.,' -]{2,80}?)(?=\s+(?:mortgage|loan|account|renewal|maturity|balance|current|offered|payment|term|amorti)|$)",
                    confidence=0.75,
                    name="lender_label",
                ),
            ),
        ),
        "mortgage_reference": FieldSpec(
            key="mortgage_reference",
            label="Masked mortgage reference",
            kind="reference",
            prompt="Confirm only the last four digits if a mortgage reference is needed.",
            patterns=(
                PatternSpec(
                    r"(?:mortgage|loan|account)\s*(?:number|no\.?|#)\s*:?\s*([A-Z0-9 -]{5,40}?)(?=\s+(?:outstanding|balance|current|renewal|maturity|payment|term|remaining|amorti|lender)|$)",
                    confidence=0.82,
                    name="masked_reference",
                ),
            ),
        ),
    }


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def bounded_text(text: str) -> str:
    if not isinstance(text, str):
        raise OCRFieldError("OCR page text must be a string")
    if len(text) > MAX_PAGE_TEXT:
        raise OCRFieldError(f"OCR page text exceeds {MAX_PAGE_TEXT} characters")
    return text


def prepare_pages(pages: list[Any]) -> list[OCRTextPage]:
    if not isinstance(pages, list) or not pages:
        raise OCRFieldError("Supply at least one OCR text page")
    if len(pages) > MAX_PAGES:
        raise OCRFieldError(f"Supply at most {MAX_PAGES} OCR text pages")
    prepared: list[OCRTextPage] = []
    for index, item in enumerate(pages, 1):
        if isinstance(item, OCRTextPage):
            page = item
        elif isinstance(item, str):
            page = OCRTextPage(index, bounded_text(item))
        elif isinstance(item, dict):
            page_number = int(item.get("page_number") or item.get("page") or index)
            confidence = item.get("mean_confidence")
            if confidence is not None:
                confidence = float(confidence)
                if not 0 <= confidence <= 1:
                    raise OCRFieldError("mean_confidence must be between 0 and 1")
            page = OCRTextPage(page_number, bounded_text(str(item.get("text", ""))), confidence)
        else:
            raise OCRFieldError("Each OCR page must be text or an object with text")
        if page.page_number < 1 or page.page_number > 200:
            raise OCRFieldError("Page numbers must be from 1 through 200")
        prepared.append(
            OCRTextPage(
                page_number=page.page_number,
                text=page.text,
                mean_confidence=page.mean_confidence,
                source_hash=page.source_hash or text_hash(page.text),
            )
        )
    return prepared


def redact_sensitive_text(text: str) -> str:
    """Best-effort display redaction for OCR snippets and diagnostics."""
    output = str(text or "")[:800]
    output = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", output)
    output = re.sub(r"\b\d{3}[- ]?\d{3}[- ]?\d{3}\b", "[9-digit-id]", output)
    output = re.sub(
        r"(?i)\b(?:account|acct|loan|mortgage)\s*(?:number|no\.?|#)\s*:?\s*[A-Z]{0,8}\d?[A-Z0-9]*(?:-[A-Z0-9]{2,12}){1,6}\b",
        "[account-ref]",
        output,
    )
    output = re.sub(
        r"(?i)\b(?:account|acct|loan|mortgage)\s*(?:number|no\.?|#)\s*:?\s*(?:\d[ -]?){5,20}\b",
        "[account-ref]",
        output,
    )
    output = re.sub(
        r"(?i)\b(?:account|acct|loan|mortgage)\s*(?:number|no\.?|#)\s*:?\s*(?=[A-Z0-9]{6,24}\b)(?=(?:[A-Z0-9]*\d){4,})(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,24}\b",
        "[account-ref]",
        output,
    )
    output = re.sub(
        r"\b(?=[A-Z0-9-]*[A-Z])(?=(?:[A-Z0-9-]*\d){4,})[A-Z0-9]{1,10}(?:-[A-Z0-9]{2,12}){1,6}\b",
        "[account-ref]",
        output,
        flags=re.I,
    )
    output = re.sub(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[phone]", output)
    return re.sub(r"\s+", " ", output).strip()


def flatten_ocr_text(text: str) -> str:
    replacements = {
        "\u00a0": " ",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\ufb01": "fi",
        "\ufb02": "fl",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    return text.strip()


def repair_numeric_token(value: str) -> str:
    token = str(value or "").strip()
    token = token.replace("$", "").replace("CAD", "").replace("cad", "")
    token = token.replace(" ", "").replace(",", "")
    if re.search(r"\d", token):
        token = token.replace("O", "0").replace("o", "0")
        token = token.replace("I", "1").replace("l", "1").replace("|", "1")
    token = re.sub(r"(?<=\d)[Oo](?=\d)", "0", token)
    token = re.sub(r"^[Oo](?=\d)", "0", token)
    token = re.sub(r"(?<=\d)[Il|](?=\d)", "1", token)
    token = re.sub(r"^[Il|](?=\d)", "1", token)
    token = re.sub(r"(?<=\d)[Ss](?=\d{2}\b)", "5", token)
    if token.count(".") > 1:
        left, *right = token.split(".")
        token = left + "." + "".join(right)
    return token


def parse_money(value: str) -> NormalizedValue | None:
    token = repair_numeric_token(value)
    try:
        amount = Decimal(token).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or amount > Decimal("100000000"):
        return None
    return NormalizedValue(float(amount), f"{amount:.2f}")


def parse_percent(value: str) -> NormalizedValue | None:
    token = repair_numeric_token(value)
    try:
        rate = Decimal(token).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if rate < 0 or rate > Decimal("30"):
        return None
    return NormalizedValue(float(rate), f"{rate.normalize()}")


def parse_int_token(value: str) -> int | None:
    token = repair_numeric_token(value)
    if not re.fullmatch(r"\d{1,4}", token):
        return None
    return int(token)


def parse_months(raw: str, context: str) -> NormalizedValue | None:
    number = parse_int_token(raw)
    if number is None:
        return None
    lower = context.lower()
    months = number * 12 if re.search(r"\b(year|yr)", lower) else number
    if not 1 <= months <= 480:
        return None
    return NormalizedValue(months, str(months))


def parse_amortization(match: re.Match, context: str) -> NormalizedValue | None:
    years_or_months = parse_int_token(match.group(1))
    if years_or_months is None:
        return None
    lower = context.lower()
    if re.search(r"\b(year|yr)", lower):
        extra = parse_int_token(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else 0
        months = years_or_months * 12 + (extra or 0)
    else:
        months = years_or_months
    if not 1 <= months <= 480:
        return None
    return NormalizedValue(months, str(months))


def parse_date_value(value: str) -> NormalizedValue | None:
    raw = re.sub(r"\s+", " ", str(value or "").strip().replace(".", ""))
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%m/%d/%y",
        "%d/%m/%y",
    )
    warnings: list[str] = []
    if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", raw):
        left, right, *_ = re.split(r"[-/]", raw)
        if int(left) <= 12 and int(right) <= 12:
            warnings.append("ambiguous_numeric_date")
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            if parsed < date(2000, 1, 1) or parsed > date(2100, 12, 31):
                return None
            return NormalizedValue(parsed.isoformat(), parsed.isoformat(), tuple(warnings))
        except ValueError:
            continue
    return None


def parse_enum(value: str, allowed: tuple[str, ...]) -> NormalizedValue | None:
    normalized = str(value or "").strip().lower().replace(" ", "-")
    normalized = normalized.replace("bi-weekly", "biweekly")
    normalized = normalized.replace("semi-monthly", "semi-monthly")
    if normalized == "accelerated-biweekly":
        normalized = "accelerated-biweekly"
    if normalized in allowed:
        return NormalizedValue(normalized, normalized)
    return None


def parse_reference(value: str) -> NormalizedValue | None:
    compact = re.sub(r"[^A-Za-z0-9]", "", str(value or ""))
    if len(compact) < 5:
        return None
    return NormalizedValue("****" + compact[-4:], "****" + compact[-4:], ("masked_sensitive_reference",))


def parse_text(value: str) -> NormalizedValue | None:
    cleaned = redact_sensitive_text(value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-")
    if not cleaned or len(cleaned) > 120:
        return None
    return NormalizedValue(cleaned, cleaned)


def normalize_match(spec: FieldSpec, match: re.Match) -> NormalizedValue | None:
    raw = match.group(1)
    context = match.group(0)
    if spec.kind == "money":
        return parse_money(raw)
    if spec.kind == "percent":
        return parse_percent(raw)
    if spec.kind == "months":
        return parse_months(raw, context)
    if spec.kind == "amortization":
        return parse_amortization(match, context)
    if spec.kind == "date":
        return parse_date_value(raw)
    if spec.kind == "enum":
        return parse_enum(raw, spec.allowed_values)
    if spec.kind == "reference":
        return parse_reference(raw)
    if spec.kind == "text":
        return parse_text(raw)
    raise OCRFieldError(f"Unknown OCR field kind: {spec.kind}")


def confidence_label(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def excerpt_for(text: str, start: int, end: int, radius: int = 90) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return redact_sensitive_text(text[left:right])


def confidence_adjustment(page: OCRTextPage, value: NormalizedValue) -> tuple[float, list[str]]:
    adjustment = 0.0
    warnings = list(value.warnings)
    if page.mean_confidence is not None:
        if page.mean_confidence < 0.45:
            adjustment -= 0.22
            warnings.append("low_page_ocr_confidence")
        elif page.mean_confidence < 0.65:
            adjustment -= 0.1
            warnings.append("medium_page_ocr_confidence")
        elif page.mean_confidence > 0.85:
            adjustment += 0.04
    return adjustment, warnings


def candidate_from_match(spec: FieldSpec, pattern: PatternSpec,
                         page: OCRTextPage, text: str, match: re.Match) -> FieldCandidate | None:
    normalized = normalize_match(spec, match)
    if normalized is None:
        return None
    adjustment, warnings = confidence_adjustment(page, normalized)
    score = max(0.05, min(0.99, pattern.confidence + adjustment))
    return FieldCandidate(
        key=spec.key,
        label=spec.label,
        value=normalized.value,
        display_value=normalized.display,
        page=page.page_number,
        excerpt=excerpt_for(text, match.start(), match.end()),
        confidence=confidence_label(score),
        confidence_score=round(score, 4),
        source="ocr_text",
        pattern=pattern.name,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def dedupe_candidates(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    seen = set()
    output: list[FieldCandidate] = []
    for item in sorted(candidates, key=lambda c: (-c.confidence_score, c.page, c.display_value)):
        key = (item.key, item.display_value, item.page)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def find_candidates(pages: list[OCRTextPage]) -> dict[str, list[FieldCandidate]]:
    specs = field_specs()
    grouped: dict[str, list[FieldCandidate]] = {key: [] for key in specs}
    for page in pages:
        flattened = flatten_ocr_text(page.text)
        if not flattened:
            continue
        for spec in specs.values():
            for pattern in spec.patterns:
                for match in re.finditer(pattern.expression, flattened, pattern.flags):
                    candidate = candidate_from_match(spec, pattern, page, flattened, match)
                    if candidate:
                        grouped[spec.key].append(candidate)
    return {key: dedupe_candidates(value) for key, value in grouped.items() if value}


def distinct_values(candidates: list[FieldCandidate]) -> list[str]:
    values = []
    for candidate in candidates:
        if candidate.display_value not in values:
            values.append(candidate.display_value)
    return values


def choose_best(candidates: list[FieldCandidate]) -> FieldCandidate:
    ordered = sorted(candidates, key=lambda c: (-c.confidence_score, c.page, c.pattern))
    best = ordered[0]
    close_alternatives = [item for item in ordered if item.confidence_score >= best.confidence_score - 0.12]
    values = distinct_values(close_alternatives)
    if len(values) > 1:
        score = max(0.05, best.confidence_score - 0.14)
        best = replace(
            best,
            confidence_score=round(score, 4),
            confidence=confidence_label(score),
            warnings=tuple(dict.fromkeys([*best.warnings, "conflicting_ocr_candidates"])),
        )
    return best


def normalize_correction(spec: FieldSpec, raw_value: Any) -> FieldCandidate:
    fake_text = f"{spec.label}: {raw_value}"
    if spec.kind == "amortization":
        match = re.search(r"([0-9OIl]{1,3})", fake_text)
        normalized = parse_months(match.group(1), "months") if match else None
    elif spec.kind == "months":
        match = re.search(r"([0-9OIl]{1,3})", fake_text)
        normalized = parse_months(match.group(1), "months") if match else None
    elif spec.kind == "money":
        normalized = parse_money(str(raw_value))
    elif spec.kind == "percent":
        normalized = parse_percent(str(raw_value))
    elif spec.kind == "date":
        normalized = parse_date_value(str(raw_value))
    elif spec.kind == "enum":
        normalized = parse_enum(str(raw_value), spec.allowed_values)
    elif spec.kind == "reference":
        normalized = parse_reference(str(raw_value))
    else:
        normalized = parse_text(str(raw_value))
    if normalized is None:
        raise OCRFieldError(f"Manual correction for {spec.key} is invalid")
    return FieldCandidate(
        key=spec.key,
        label=spec.label,
        value=normalized.value,
        display_value=normalized.display,
        page=0,
        excerpt="Manual reviewer correction",
        confidence="high",
        confidence_score=0.99,
        source="manual_review",
        pattern="manual_correction",
        warnings=tuple(dict.fromkeys(normalized.warnings)),
    )


def apply_corrections(fields: dict[str, FieldCandidate],
                      corrections: dict[str, Any] | None) -> tuple[dict[str, FieldCandidate], list[dict]]:
    if not corrections:
        return fields, []
    if not isinstance(corrections, dict):
        raise OCRFieldError("Corrections must be an object keyed by field name")
    if len(corrections) > MAX_CORRECTIONS:
        raise OCRFieldError(f"Supply at most {MAX_CORRECTIONS} manual corrections")
    specs = field_specs()
    updated = dict(fields)
    audit = []
    for key, value in corrections.items():
        if key not in specs:
            raise OCRFieldError(f"Unknown correction field: {key}")
        corrected = normalize_correction(specs[key], value)
        previous = updated.get(key)
        updated[key] = corrected
        audit.append(
            {
                "field": key,
                "previous": previous.display_value if previous else None,
                "new": corrected.display_value,
                "source": "manual_review",
            }
        )
    return updated, audit


def document_metrics(pages: list[OCRTextPage]) -> dict:
    text = "\n".join(page.text for page in pages)
    redacted = redact_sensitive_text(text)
    words = re.findall(r"\b[A-Za-z0-9]{2,}\b", text)
    digit_ratio = sum(ch.isdigit() for ch in text) / max(1, len(text))
    confidence_values = [p.mean_confidence for p in pages if p.mean_confidence is not None]
    return {
        "pages": len(pages),
        "characters": len(text),
        "word_count": len(words),
        "digit_ratio": round(digit_ratio, 4),
        "mean_page_confidence": round(sum(confidence_values) / len(confidence_values), 4)
        if confidence_values else None,
        "redactions_applied": redacted.count("["),
        "empty_pages": sum(1 for page in pages if not page.text.strip()),
    }


def mortgage_draft(fields: dict[str, FieldCandidate]) -> dict:
    allowed = {
        "balance",
        "offered_rate",
        "current_rate",
        "contract_rate",
        "posted_rate",
        "contract_discount",
        "amortization_months",
        "term_months",
        "maturity_date",
        "mortgage_start_date",
        "frequency",
        "lender",
    }
    return {key: fields[key].value for key in allowed if key in fields}


def review_item(spec: FieldSpec, candidate: FieldCandidate | None,
                alternatives: list[FieldCandidate]) -> dict:
    if candidate is None:
        status = "missing_required" if spec.required else "missing_optional"
        blocking = spec.required
        value = None
        confidence = None
        page = None
        warnings = []
    else:
        warnings = list(candidate.warnings)
        low = candidate.confidence != "high"
        conflict = "conflicting_ocr_candidates" in candidate.warnings
        status = "needs_review" if low or conflict else "ready"
        blocking = spec.required and (low or conflict)
        value = candidate.display_value
        confidence = candidate.confidence
        page = candidate.page or None
    return {
        "field": spec.key,
        "label": spec.label,
        "status": status,
        "blocking": blocking,
        "value": value,
        "confidence": confidence,
        "page": page,
        "prompt": spec.prompt,
        "warnings": warnings,
        "alternative_count": max(0, len(distinct_values(alternatives)) - (1 if candidate else 0)),
    }


def build_review_packet(fields: dict[str, FieldCandidate],
                        grouped: dict[str, list[FieldCandidate]]) -> list[dict]:
    packet = []
    for spec in field_specs().values():
        packet.append(review_item(spec, fields.get(spec.key), grouped.get(spec.key, [])))
    return packet


def review_status(packet: list[dict]) -> str:
    if any(item["blocking"] for item in packet):
        return "blocked"
    if any(item["status"] == "needs_review" for item in packet):
        return "review_recommended"
    return "ready"


def page_previews(pages: list[OCRTextPage], limit: int = 3) -> list[dict]:
    previews = []
    for page in pages[:limit]:
        previews.append(
            {
                "page": page.page_number,
                "text_sha256": page.source_hash,
                "preview": redact_sensitive_text(flatten_ocr_text(page.text)[:600]),
            }
        )
    return previews


def extraction_warnings(pages: list[OCRTextPage], fields: dict[str, FieldCandidate],
                        grouped: dict[str, list[FieldCandidate]]) -> list[str]:
    warnings: list[str] = []
    metrics = document_metrics(pages)
    if metrics["empty_pages"]:
        warnings.append("one_or_more_ocr_pages_are_empty")
    if metrics["word_count"] < 20:
        warnings.append("ocr_text_is_very_short")
    missing = [key for key in REQUIRED_FIELDS if key not in fields]
    for key in missing:
        warnings.append(f"missing_required_field:{key}")
    for key, candidates in grouped.items():
        if len(distinct_values(candidates)) > 1:
            warnings.append(f"conflicting_candidates:{key}")
    return warnings


def extract_ocr_fields(pages: list[Any], *, filename: str = "ocr.txt",
                       corrections: dict[str, Any] | None = None,
                       min_confidence: float = 0.0) -> dict:
    if not 0 <= min_confidence <= 1:
        raise OCRFieldError("min_confidence must be between 0 and 1")
    prepared = prepare_pages(pages)
    grouped = find_candidates(prepared)
    selected: dict[str, FieldCandidate] = {}
    for key, candidates in grouped.items():
        best = choose_best(candidates)
        if best.confidence_score >= min_confidence:
            selected[key] = best
    selected, manual_audit = apply_corrections(selected, corrections)
    packet = build_review_packet(selected, grouped)
    missing_required = [item["field"] for item in packet if item["status"] == "missing_required"]
    fields_public = {key: candidate.public() for key, candidate in sorted(selected.items())}
    alternatives = {
        key: [candidate.public() for candidate in candidates[:5]]
        for key, candidates in sorted(grouped.items())
        if len(candidates) > 1
    }
    return {
        "provider": "deterministic-ocr-fields-v10",
        "filename": str(filename or "ocr.txt")[:120],
        "pages": [page.public() for page in prepared],
        "fields": fields_public,
        "alternatives": alternatives,
        "mortgage_draft": mortgage_draft(selected),
        "missing_required": missing_required,
        "review_packet": packet,
        "review_status": review_status(packet),
        "manual_corrections": manual_audit,
        "metrics": document_metrics(prepared),
        "warnings": extraction_warnings(prepared, selected, grouped),
        "preview": page_previews(prepared),
        "notice": "OCR-derived fields must be manually verified against the source document.",
    }


def summarize_review_decision(extraction: dict) -> dict:
    packet = extraction.get("review_packet", [])
    blocking = [item for item in packet if item.get("blocking")]
    ready = [item for item in packet if item.get("status") == "ready"]
    needs_review = [item for item in packet if item.get("status") == "needs_review"]
    return {
        "status": extraction.get("review_status", "unknown"),
        "ready_fields": [item["field"] for item in ready],
        "needs_review_fields": [item["field"] for item in needs_review],
        "blocking_fields": [item["field"] for item in blocking],
        "can_prefill_mortgage_form": not blocking,
        "field_count": len(extraction.get("fields", {})),
        "manual_correction_count": len(extraction.get("manual_corrections", [])),
    }
