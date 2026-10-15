"""Canadian mortgage term explanations for OCR-understood documents."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from ..domain.mortgage_math import PER_YEAR, periodic_rate, scheduled_payment


class MortgageTermError(ValueError):
    """Term explanation inputs are not usable."""


@dataclass(frozen=True)
class MortgageTerm:
    key: str
    label: str
    plain_language: str
    calculated_how: str
    why_it_matters: str
    review_tip: str

    def public(self) -> dict:
        return asdict(self)


def canadian_mortgage_glossary() -> dict[str, MortgageTerm]:
    return {
        "balance": MortgageTerm(
            "balance",
            "Mortgage balance",
            "The unpaid principal amount at the date shown on the document.",
            "Usually copied from the lender statement. It is not recalculated from OCR unless an amortization schedule is available.",
            "This is the starting debt used for payment, renewal and switching comparisons.",
            "Confirm the balance date because payout balances change daily as interest accrues.",
        ),
        "contract_rate": MortgageTerm(
            "contract_rate",
            "Contract rate",
            "The interest rate written into the mortgage contract for the term.",
            "For fixed-rate payment estimates in Canada, the nominal annual rate is converted using semi-annual compounding before payment frequency is applied.",
            "It drives scheduled payment estimates and can affect penalty wording.",
            "Do not confuse contract rate with posted rate, APR, comparison rate, or a future renewal offer.",
        ),
        "posted_rate": MortgageTerm(
            "posted_rate",
            "Posted rate",
            "A lender's reference rate before a discount is applied.",
            "Posted rate is usually read from the contract or lender table, not inferred unless contract rate and discount are both present.",
            "Many fixed-rate IRD penalty clauses compare your discounted rate against a posted or comparison rate.",
            "Ask the lender which posted rate and date are used in any penalty calculation.",
        ),
        "contract_discount": MortgageTerm(
            "contract_discount",
            "Contract discount",
            "The reduction from posted rate that produced the contract rate.",
            "Simple check: posted rate minus contract rate should approximately equal the discount, if all three are from the same context.",
            "Discount wording matters for interest-rate-differential penalties and renewal negotiation.",
            "Verify whether the discount applies only to the original term or carries into a blend/renewal calculation.",
        ),
        "offered_rate": MortgageTerm(
            "offered_rate",
            "Renewal offered rate",
            "The rate the lender is offering for the next term.",
            "Payment estimates use the offered rate, remaining amortization and payment frequency.",
            "This is the rate compared against alternatives, but it is not a guarantee of approval elsewhere.",
            "Confirm whether fees, insurance, taxes or conditions are attached to the offer.",
        ),
        "current_rate": MortgageTerm(
            "current_rate",
            "Current rate",
            "The rate on the mortgage before renewal or before a proposed switch.",
            "Used as context for payment changes and possible penalty language.",
            "A large jump between current and renewal rate can explain payment shock.",
            "Check whether the document labels this as current, existing, contract, posted or renewal rate.",
        ),
        "term_months": MortgageTerm(
            "term_months",
            "Term",
            "The length of time the rate and core contract conditions apply.",
            "Usually expressed in months or years. A 3-year term is 36 months; a 5-year term is 60 months.",
            "Term is not the same as amortization. The mortgage can renew many times before it is fully repaid.",
            "Compare term length with maturity date and mortgage start date when both are visible.",
        ),
        "amortization_months": MortgageTerm(
            "amortization_months",
            "Remaining amortization",
            "The remaining time over which payments are scheduled to repay the mortgage.",
            "Payment formulas use amortization as the number of repayment periods, not the term length.",
            "Longer amortization lowers payment but usually increases total interest over time.",
            "Confirm whether the document says original amortization or remaining amortization.",
        ),
        "maturity_date": MortgageTerm(
            "maturity_date",
            "Maturity date",
            "The date the current term ends.",
            "When a mortgage start date is known, months between start and maturity should roughly match the term.",
            "This anchors renewal deadlines, switch timing and whether a penalty may apply.",
            "Ask whether documents must be signed before this date to avoid automatic renewal.",
        ),
        "mortgage_start_date": MortgageTerm(
            "mortgage_start_date",
            "Mortgage start date",
            "The date the mortgage term, funding, advance or interest adjustment began.",
            "Used with maturity date to infer term timing and identify the contract period.",
            "It helps interpret discounts, posted-rate tables and penalty formulas.",
            "Labels vary: mortgage date, funding date, advance date, registration date and interest adjustment date can mean different things.",
        ),
        "payment_amount": MortgageTerm(
            "payment_amount",
            "Regular payment",
            "The amount paid each payment period.",
            "Estimated from balance, rate, amortization and frequency; actual lender payment can differ because of taxes, insurance, rounding or contract conventions.",
            "Payment comparisons are only meaningful when frequency and included items are the same.",
            "Separate principal-and-interest from property tax or insurance components before comparing offers.",
        ),
        "frequency": MortgageTerm(
            "frequency",
            "Payment frequency",
            "How often payments are made, such as monthly, semi-monthly, biweekly or weekly.",
            "The payment formula uses periods per year. Accelerated biweekly/weekly are based on monthly payment halves/quarters.",
            "Frequency changes cash flow and principal paydown speed.",
            "Confirm whether biweekly is regular or accelerated.",
        ),
        "interest_rate_differential": MortgageTerm(
            "interest_rate_differential",
            "Interest rate differential (IRD)",
            "A fixed-rate prepayment penalty concept comparing your contract economics with a lender comparison rate.",
            "Exact formulas are lender-specific. A simplified review compares rate differences, remaining term and balance, but the lender payout statement controls.",
            "IRD can make switching expensive even when a new rate looks better.",
            "Ask for a written payout statement and the comparison rate/date used in the formula.",
        ),
    }


def glossary_public() -> dict:
    terms = canadian_mortgage_glossary()
    return {
        "provider": "canadian-mortgage-terms-v11",
        "terms": [terms[key].public() for key in sorted(terms)],
        "calculation_note": "Fixed-rate estimates use Canadian nominal annual rates compounded semi-annually, then converted to the payment frequency.",
    }


def _value(extraction: dict, key: str) -> Any:
    payload = extraction.get("fields", {}).get(key, {})
    return payload.get("value")


def _display(extraction: dict, key: str) -> str | None:
    payload = extraction.get("fields", {}).get(key, {})
    value = payload.get("display_value")
    return str(value) if value is not None else None


def contract_discount_math(posted_rate: Any, contract_rate: Any,
                           contract_discount: Any = None) -> dict | None:
    if posted_rate is None or contract_rate is None:
        return None
    posted = float(posted_rate)
    contract = float(contract_rate)
    implied = round(posted - contract, 4)
    result = {
        "posted_rate": round(posted, 4),
        "contract_rate": round(contract, 4),
        "implied_discount": implied,
        "formula": "posted_rate - contract_rate = implied_discount",
    }
    if contract_discount is not None:
        discount = float(contract_discount)
        result["document_discount"] = round(discount, 4)
        result["difference"] = round(abs(implied - discount), 4)
        result["status"] = "matches" if result["difference"] <= 0.08 else "review"
        result["explanation"] = (
            "The discount in the document is close to posted rate minus contract rate."
            if result["status"] == "matches"
            else "The discount in the document does not match posted rate minus contract rate closely enough for automatic trust."
        )
    else:
        result["status"] = "inferred_only"
        result["explanation"] = "The document did not expose a discount label, but posted and contract rates imply one."
    return result


def payment_formula_explanation(balance: Any, rate: Any, amortization_months: Any,
                                frequency: str = "monthly",
                                rate_type: str = "fixed") -> dict | None:
    if balance is None or rate is None or amortization_months is None:
        return None
    frequency = str(frequency or "monthly")
    if frequency not in PER_YEAR:
        raise MortgageTermError("Unsupported payment frequency")
    payment = scheduled_payment(
        float(balance),
        float(rate),
        int(amortization_months),
        frequency,
        rate_type,
    )
    periods = PER_YEAR[frequency]
    periodic = periodic_rate(float(rate), periods, rate_type)
    return {
        "balance": round(float(balance), 2),
        "annual_rate_percent": round(float(rate), 4),
        "amortization_months": int(amortization_months),
        "frequency": frequency,
        "periods_per_year": periods,
        "periodic_rate": round(periodic, 10),
        "estimated_payment": round(payment, 2),
        "rate_type": rate_type,
        "formula_note": (
            "For fixed rates, Canadian nominal APR is compounded semi-annually, "
            "then converted to the payment frequency before solving the annuity payment."
        ),
    }


def timeline_explanation(mortgage_start_date: Any, maturity_date: Any,
                         term_months: Any = None) -> dict | None:
    if not mortgage_start_date or not maturity_date:
        return None
    start = date.fromisoformat(str(mortgage_start_date))
    maturity = date.fromisoformat(str(maturity_date))
    months = (maturity.year - start.year) * 12 + (maturity.month - start.month)
    if maturity.day < start.day:
        months -= 1
    result = {
        "mortgage_start_date": str(mortgage_start_date),
        "maturity_date": str(maturity_date),
        "months_between": months,
        "formula": "(maturity year/month - start year/month), adjusted when maturity day is earlier",
    }
    if term_months is not None:
        result["term_months"] = int(term_months)
        result["difference_months"] = abs(months - int(term_months))
        result["status"] = "matches" if result["difference_months"] <= 2 else "review"
    else:
        result["status"] = "inferred_only"
    return result


def explain_extracted_terms(extraction: dict) -> dict:
    glossary = canadian_mortgage_glossary()
    fields = extraction.get("fields", {})
    present = []
    for key in sorted(fields):
        if key not in glossary:
            continue
        item = glossary[key].public()
        item["extracted_value"] = _display(extraction, key)
        item["source_page"] = fields[key].get("page")
        item["confidence"] = fields[key].get("confidence")
        present.append(item)
    frequency = _value(extraction, "frequency") or "monthly"
    payment = None
    try:
        payment = payment_formula_explanation(
            _value(extraction, "balance"),
            _value(extraction, "offered_rate") or _value(extraction, "contract_rate"),
            _value(extraction, "amortization_months"),
            frequency=frequency,
            rate_type="fixed",
        )
    except (ValueError, MortgageTermError):
        payment = None
    discount = contract_discount_math(
        _value(extraction, "posted_rate"),
        _value(extraction, "contract_rate"),
        _value(extraction, "contract_discount"),
    )
    timeline = None
    try:
        timeline = timeline_explanation(
            _value(extraction, "mortgage_start_date"),
            _value(extraction, "maturity_date"),
            _value(extraction, "term_months"),
        )
    except (TypeError, ValueError):
        timeline = None
    return {
        "provider": "canadian-mortgage-terms-v11",
        "present_terms": present,
        "calculations": {
            "payment_estimate": payment,
            "contract_discount": discount,
            "term_timeline": timeline,
        },
        "missing_term_context": [
            key
            for key in ("contract_rate", "posted_rate", "contract_discount", "mortgage_start_date")
            if key not in fields
        ],
        "calculation_note": "These are deterministic explanations for review, not lender payout or legal advice.",
    }
