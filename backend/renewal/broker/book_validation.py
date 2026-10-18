"""Decision gates for incomplete, inconsistent, or unverified broker records."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .book_values import (
    MAX_AMORT_MONTHS, MAX_BALANCE, MAX_PAYMENT, MAX_TERM_MONTHS,
    contract_is_open, finite_number, payment_frequency,
)


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    field: str
    message: str
    blocking: bool = True

    def as_dict(self):
        return asdict(self)


def validate_deal(deal, as_of: date) -> list[ReviewIssue]:
    issues = []

    def add(code, field, message, blocking=True):
        issues.append(ReviewIssue(code, field, message, blocking))

    if not deal.lender or not isinstance(deal.lender, str):
        add("missing_lender", "lender", "Confirm the lender before calculating a penalty.")
    for field, low, high in (
        ("balance", 0.01, MAX_BALANCE),
        ("contract_rate", 0.000001, 30),
        ("amort_months", 1, MAX_AMORT_MONTHS),
        ("term_months", 1, MAX_TERM_MONTHS),
    ):
        value = getattr(deal, field, None)
        if finite_number(value, low, high) is None:
            add("invalid_" + field, field, f"A valid {field.replace('_', ' ')} is required.")
        elif field.endswith("months") and not float(value).is_integer():
            add("fractional_months", field, "Durations must be whole months.")
    for field, low, high in (
        ("posted_rate", 0.000001, 30),
        ("discount", 0, 10),
        ("payment", 0.01, MAX_PAYMENT),
    ):
        value = getattr(deal, field, None)
        if value is not None and finite_number(value, low, high) is None:
            add("invalid_" + field, field, f"The supplied {field.replace('_', ' ')} is invalid.")
    if not deal.closing_date or not deal.maturity_date:
        add("missing_dates", "closing_date", "Confirm closing and maturity dates.")
    else:
        days = (deal.maturity_date - deal.closing_date).days
        if not 1 <= days <= 366 * 11:
            add("invalid_date_order", "maturity_date", "Maturity must follow closing by no more than eleven years.")
        elif deal.term_months:
            from ..ratewatch.ird import add_months
            expected = add_months(deal.closing_date, int(deal.term_months))
            if abs((expected - deal.maturity_date).days) > 35:
                add("term_date_conflict", "term_months", "The stated term disagrees with the closing and maturity dates.")
    if deal.rate_type not in ("fixed", "variable"):
        add("unknown_rate_type", "rate_type", "Confirm fixed or variable; no fixed-rate assumption is made.")
    if deal.is_open or contract_is_open(deal.product):
        add("open_contract", "product", "Open contracts need their own written payout quote; the closed-mortgage engine is not used.")
    if deal.balance_basis not in ("current", "original"):
        add("unknown_balance_basis", "balance_basis", "Choose current statement balance or original advance.")
    if deal.amort_basis not in ("remaining", "original"):
        add("unknown_amort_basis", "amort_basis", "Choose original or remaining amortization.")
    if deal.balance_basis == "original" and deal.amort_basis != "original":
        add("original_amort_required", "amort_basis", "Projecting the original advance requires original amortization.")
    if deal.balance_basis == "original" and deal.rate_type == "variable":
        add("variable_balance_history", "balance", "Use a current statement balance for a variable-rate mortgage.")
    if deal.balance_date and deal.balance_basis == "current" and deal.balance_date != as_of:
        add("stale_balance", "balance_date", "The statement balance date must match the review date.")
    if deal.payment is not None and not deal.frequency:
        add("payment_frequency_missing", "frequency", "A payment amount must include its payment frequency.")
    if deal.frequency and payment_frequency(deal.frequency) is None:
        add("unknown_frequency", "frequency", "The supplied payment frequency is not recognized.")
    if deal.source == "ocr" and not deal.review_confirmed:
        add("ocr_unverified", "review_confirmed", "Verify OCR fields against the document before making a recommendation.")
    if deal.status:
        status = re.sub(r"[^a-z]+", " ", deal.status.lower()).strip()
        if status in {"cancelled", "canceled", "declined", "withdrawn", "draft", "submitted", "approved", "not funded"}:
            add("not_funded_status", "status", "Only a confirmed funded mortgage can be reviewed for a break.")
    if deal.posted_rate is not None and deal.contract_rate is not None:
        inferred = deal.posted_rate - deal.contract_rate
        if inferred < 0:
            add("negative_discount", "posted_rate", "Original posted rate is below the contract rate.")
        elif deal.discount is not None and abs(inferred - deal.discount) > 0.005:
            add("discount_conflict", "discount", "Stated discount conflicts with posted rate minus contract rate.")
    for message in deal.issues:
        if message.startswith(("invalid ", "ambiguous ", "conflicting ")):
            add("import_value", "import", message)
    return issues


def normalized_lender_words(name) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def lender_alias_matches(name: str, alias: str) -> bool:
    normalized = normalized_lender_words(name)
    needle = normalized_lender_words(alias)
    if not needle:
        return False
    return (" " + needle + " ") in (" " + normalized + " ")


def source_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        match = re.search(r"\b(?:wayback|common crawl)\s+(\d{8})\b", value.lower())
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y%m%d").date()
            except ValueError:
                pass
    return None


def offer_issues(offer: dict, as_of: date, maximum_age_days=14) -> list[ReviewIssue]:
    issues = []
    rate = finite_number(offer.get("rate"), 0.5, 15)
    if rate is None:
        issues.append(ReviewIssue("invalid_offer_rate", "rate", "Offer rate must be finite and between 0.5% and 15%."))
    if not offer.get("labelled", False):
        issues.append(ReviewIssue("unlabelled_offer", "rate", "An unlabelled rate is not a verified fixed-rate offer."))
    captured = source_date(offer.get("as_of"))
    if captured is None:
        issues.append(ReviewIssue("offer_date_missing", "as_of", "Offer source date is missing or invalid."))
    else:
        age = (as_of - captured).days
        if age < 0:
            issues.append(ReviewIssue("future_offer", "as_of", "Offer was captured after the requested review date."))
        elif age > maximum_age_days:
            issues.append(ReviewIssue("offer_expired", "as_of", "Offer source is older than the allowed freshness window."))
        elif age > 1:
            issues.append(ReviewIssue("cached_offer", "as_of", f"Offer is {age} days old; obtain a current written quote.", False))
    posted = offer.get("posted")
    if posted is not None and rate is not None:
        posted = finite_number(posted, 0.5, 30)
        if posted is None or posted < rate:
            issues.append(ReviewIssue("offer_labels_conflict", "rate", "Special and posted rate labels are inconsistent."))
    return issues


def validate_rate_table(table: dict) -> bool:
    supported = {6, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120}
    return bool(table) and all(
        isinstance(term, int) and not isinstance(term, bool) and term in supported
        and finite_number(rate, 0.5, 30) is not None
        for term, rate in table.items()
    )


def summarize_diagnostics(results: list[dict]) -> dict:
    counts = {}
    blocked = 0
    estimated = 0
    for result in results:
        if any(issue.get("blocking") for issue in result.get("validation", [])):
            blocked += 1
        if result.get("method_status") == "estimate":
            estimated += 1
        for issue in result.get("validation", []):
            code = issue["code"]
            counts[code] = counts.get(code, 0) + 1
    return {
        "blocked_deals": blocked,
        "estimated_methods": estimated,
        "issue_counts": dict(sorted(counts.items())),
        "recommendations_are_quotes": False,
    }


def safe_review_date(value: date | None) -> date:
    result = value or date.today()
    if not isinstance(result, date) or not date(1990, 1, 1) <= result <= date(2100, 12, 31):
        raise ValueError("review date must be between 1990 and 2100")
    return result


def unique_deals(deals) -> tuple[list, list[dict]]:
    seen = {}
    accepted = []
    duplicates = []
    for index, deal in enumerate(deals):
        identifier = deal.deal_id.strip().casefold()
        if identifier in seen:
            duplicates.append({
                "deal_id": identifier,
                "row": index + 1,
                "first_row": seen[identifier],
                "reason": "Repeated deal identifier: omitted to prevent counting savings twice.",
            })
            continue
        seen[identifier] = index + 1
        accepted.append(deal)
    return accepted, duplicates
