# V11 Canadian Mortgage Math and Code Walkthrough

## Abstract

Renewal Radar V11 adds a deterministic document-understanding layer for Canadian
mortgage renewal documents. The goal is not to replace lender calculations or
legal review. The goal is to read OCR text, identify terms such as contract
rate, posted rate, contract discount, term, amortization, maturity date and
interest-rate-differential language, then explain how those terms relate to the
math already used by the application.

The implementation is intentionally conservative:

- OCR text is treated as evidence that needs review, not truth.
- Raw OCR text is not stored in V11 review sessions.
- Financial fields are linked back to redacted snippets and page hashes.
- Canadian fixed-rate payment estimates use nominal annual rates compounded
  semi-annually, matching the existing project math.
- Contract discount math is checked only when the document exposes posted rate
  and contract rate.

## Symbols

Let:

- `B` be outstanding balance.
- `j` be the nominal annual fixed mortgage rate as a decimal.
- `f` be payments per year.
- `N` be the number of payments over the amortization.
- `i_f` be the periodic rate for payment frequency `f`.
- `P` be the scheduled payment per period.
- `R_posted` be the lender posted rate.
- `R_contract` be the contract rate.
- `D_contract` be the contract discount.
- `T_start` be the mortgage start, funding, advance or interest-adjustment date.
- `T_maturity` be the maturity date.

## Canadian Fixed-Rate Periodic Rate

Canadian fixed-rate mortgages are commonly quoted as nominal annual rates
compounded semi-annually. To estimate payments at a chosen payment frequency,
the app converts the semi-annual compounding convention to the payment-period
rate:

```text
i_f = (1 + j / 2)^(2 / f) - 1
```

This is the same convention used in `backend/renewal/domain/mortgage_math.py`.

For variable-rate estimates, the app's existing math uses nominal monthly
compounding by default:

```text
i_f = (1 + j / 12)^(12 / f) - 1
```

Actual lender contracts can differ. The app therefore presents estimates and
review checks, not lender-certified payout numbers.

## Scheduled Payment Formula

For a balance `B`, periodic rate `i_f`, and `N` total payment periods:

```text
P = B * i_f / (1 - (1 + i_f)^(-N))
```

If `i_f = 0`, the payment reduces to:

```text
P = B / N
```

V11 uses this formula only to explain and sanity-check document numbers. If the
observed payment differs from the estimate, that does not automatically mean the
document is wrong. The payment may include taxes, insurance, different rounding,
an accelerated frequency, or lender-specific conventions.

## Contract Rate, Posted Rate and Discount

Many Canadian mortgage documents distinguish the posted rate from the contract
rate. A common relationship is:

```text
R_posted - R_contract = D_contract
```

Example:

```text
5.69% posted rate - 4.39% contract rate = 1.30% contract discount
```

V11 checks this relationship when all values are found. If the discount does not
match within a small tolerance, the result becomes a review item because the
labels may refer to different dates, products, terms, or OCR may have misread a
number.

## Term, Amortization and Dates

Term is the period during which the rate and contract conditions apply. It is
not the same as amortization.

Amortization is the schedule used to repay the mortgage balance over time. A
mortgage can have a 60-month term and a 240-month remaining amortization.

When OCR finds both mortgage start date and maturity date, V11 checks:

```text
months_between(T_start, T_maturity) approximately equals term_months
```

The check allows a small gap because documents may use funding date,
registration date, interest-adjustment date, first-payment date or term-start
date differently.

## Interest Rate Differential

Interest rate differential, or IRD, is lender-specific. V11 does not calculate a
binding IRD penalty from OCR text. Instead, it detects IRD language and asks for
review:

- Which comparison or posted rate is used?
- Which date is used for the comparison rate?
- Is the penalty the greater of IRD and three-month interest?
- Is a contract discount involved?
- Is there a written payout statement?

The existing penalty engine can estimate scenarios, but a lender payout
statement controls the actual amount.

## Line-by-Line Code Companion

This section explains the key V11 calculation helper in
`backend/renewal/ocr/mortgage_terms.py`. The comments are written as if each line
were being read aloud in a code review.

### Imports

```python
from __future__ import annotations
```

Use modern type-hint behavior without requiring all annotations to be evaluated
at import time.

```python
from dataclasses import asdict, dataclass
```

Use dataclasses for small immutable term-definition records, and `asdict` to
turn those records into API-safe dictionaries.

```python
from datetime import date
```

Use `date.fromisoformat()` and date arithmetic for mortgage start and maturity
timeline checks.

```python
from typing import Any
```

Allow helper functions to accept values coming from JSON extraction payloads,
where numbers may arrive as `int`, `float`, `str` or `None`.

```python
from ..domain.mortgage_math import PER_YEAR, periodic_rate, scheduled_payment
```

Reuse the app's existing Canadian mortgage math instead of duplicating a second
formula implementation.

### Error Class

```python
class MortgageTermError(ValueError):
    """Term explanation inputs are not usable."""
```

Create a controlled exception type for bad term-calculation requests.

### Term Definition Dataclass

```python
@dataclass(frozen=True)
class MortgageTerm:
```

Define an immutable term description, so glossary entries cannot be accidentally
mutated while building a response.

```python
    key: str
```

Store the machine-readable field name, such as `contract_rate`.

```python
    label: str
```

Store the user-facing label, such as `Contract rate`.

```python
    plain_language: str
```

Explain the term in everyday mortgage language.

```python
    calculated_how: str
```

Explain the formula, source, or relationship used for the term.

```python
    why_it_matters: str
```

Explain why the borrower or broker should care about the term.

```python
    review_tip: str
```

Give the human reviewer a concrete verification prompt.

```python
    def public(self) -> dict:
        return asdict(self)
```

Expose the dataclass as a JSON-friendly dictionary for API responses.

### Contract Discount Math

```python
def contract_discount_math(posted_rate: Any, contract_rate: Any,
                           contract_discount: Any = None) -> dict | None:
```

Define a helper that checks the relationship between posted rate, contract rate
and discount. Return `None` if the minimum inputs are missing.

```python
    if posted_rate is None or contract_rate is None:
        return None
```

Do not infer a discount unless both posted and contract rates are present.

```python
    posted = float(posted_rate)
```

Convert the posted rate to a numeric value.

```python
    contract = float(contract_rate)
```

Convert the contract rate to a numeric value.

```python
    implied = round(posted - contract, 4)
```

Compute the implied discount and round to four decimal places.

```python
    result = {
        "posted_rate": round(posted, 4),
        "contract_rate": round(contract, 4),
        "implied_discount": implied,
        "formula": "posted_rate - contract_rate = implied_discount",
    }
```

Build the result object with both the source numbers and the formula used.

```python
    if contract_discount is not None:
```

If OCR found an explicit discount, compare it against the implied discount.

```python
        discount = float(contract_discount)
```

Convert the document's discount value to a number.

```python
        result["document_discount"] = round(discount, 4)
```

Record the discount as written in the document.

```python
        result["difference"] = round(abs(implied - discount), 4)
```

Compute the absolute gap between implied and written discount.

```python
        result["status"] = "matches" if result["difference"] <= 0.08 else "review"
```

Accept small OCR or rounding noise. Larger differences require human review.

```python
        result["explanation"] = (
            "The discount in the document is close to posted rate minus contract rate."
            if result["status"] == "matches"
            else "The discount in the document does not match posted rate minus contract rate closely enough for automatic trust."
        )
```

Attach a plain-language explanation based on the status.

```python
    else:
        result["status"] = "inferred_only"
        result["explanation"] = "The document did not expose a discount label, but posted and contract rates imply one."
```

If no explicit discount was found, say that the discount is inferred only.

```python
    return result
```

Return the calculation packet.

### Payment Formula Explanation

```python
def payment_formula_explanation(balance: Any, rate: Any, amortization_months: Any,
                                frequency: str = "monthly",
                                rate_type: str = "fixed") -> dict | None:
```

Define a helper that explains the payment estimate inputs and formula.

```python
    if balance is None or rate is None or amortization_months is None:
        return None
```

Do not produce a payment estimate unless the core inputs are present.

```python
    frequency = str(frequency or "monthly")
```

Default missing frequency to monthly, which is the most common mortgage-payment
presentation.

```python
    if frequency not in PER_YEAR:
        raise MortgageTermError("Unsupported payment frequency")
```

Reject unsupported frequencies before doing math.

```python
    payment = scheduled_payment(
        float(balance),
        float(rate),
        int(amortization_months),
        frequency,
        rate_type,
    )
```

Call the existing payment engine with numeric balance, rate, amortization,
frequency and rate type.

```python
    periods = PER_YEAR[frequency]
```

Look up how many payment periods occur per year.

```python
    periodic = periodic_rate(float(rate), periods, rate_type)
```

Compute the periodic rate using the Canadian compounding convention already
implemented by the project.

```python
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
```

Return the inputs, derived periodic rate, estimated payment and a note that
explains the formula in Canadian mortgage terms.

### Timeline Explanation

```python
def timeline_explanation(mortgage_start_date: Any, maturity_date: Any,
                         term_months: Any = None) -> dict | None:
```

Define a helper that checks whether mortgage start, maturity and term appear to
belong to the same timeline.

```python
    if not mortgage_start_date or not maturity_date:
        return None
```

Do not run timeline math unless both dates exist.

```python
    start = date.fromisoformat(str(mortgage_start_date))
```

Parse the mortgage start date.

```python
    maturity = date.fromisoformat(str(maturity_date))
```

Parse the maturity date.

```python
    months = (maturity.year - start.year) * 12 + (maturity.month - start.month)
```

Compute the month difference using year/month arithmetic.

```python
    if maturity.day < start.day:
        months -= 1
```

Adjust by one month when the maturity day falls earlier in the month than the
start day.

```python
    result = {
        "mortgage_start_date": str(mortgage_start_date),
        "maturity_date": str(maturity_date),
        "months_between": months,
        "formula": "(maturity year/month - start year/month), adjusted when maturity day is earlier",
    }
```

Build the timeline explanation result.

```python
    if term_months is not None:
```

If OCR also found the term length, compare it with the date span.

```python
        result["term_months"] = int(term_months)
```

Record the stated term.

```python
        result["difference_months"] = abs(months - int(term_months))
```

Compute the gap between implied and stated term.

```python
        result["status"] = "matches" if result["difference_months"] <= 2 else "review"
```

Allow a small tolerance because mortgage date labels can mean funding date,
registration date, first payment date or interest-adjustment date.

```python
    else:
        result["status"] = "inferred_only"
```

If no stated term exists, mark the timeline as inferred only.

```python
    return result
```

Return the timeline explanation.

## What The Code Does Not Claim

- It does not certify lender terms.
- It does not calculate a binding IRD payout.
- It does not know every lender's contract convention.
- It does not store raw OCR text in review sessions.
- It does not remove the need for a borrower, broker or lawyer to verify the
  original document.

## Practical Review Checklist

1. Confirm the document type: renewal offer, payout statement, annual statement
   or rate quote.
2. Confirm mortgage start date, maturity date and term belong to the same term.
3. Confirm the contract rate is not being confused with renewal offered rate.
4. Confirm posted rate and discount are from the same date and product.
5. If IRD appears, request the written payout statement and comparison rate.
6. Separate principal-and-interest payment from taxes and insurance.
7. Confirm payment frequency, especially regular versus accelerated biweekly.
8. Treat all OCR-derived fields as review candidates until approved.
