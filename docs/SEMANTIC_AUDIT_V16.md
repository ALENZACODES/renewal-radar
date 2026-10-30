# V16: understanding document details through evidence

A mortgage renewal document can mention the original contract, the next term,
and a possible payout in the same file. One rate or date cannot represent all
three. V16 records each fact as `scope.field`, with its page, line, excerpt,
confidence, and source-text hash. Scope is original, renewal, payout, or
unspecified. Unassigned context produces a review item.

## Reading and resolving

`semantic_evidence_v16.py` defines label and unit rules. `validate_pages` checks
page limits and duplicate page numbers. `canonical_text` repairs documented
label spelling variants and typography, while leaving numeric repair visible.
`extract_semantic_mentions` reads explicit labels and local section headings.
Headings reset at page boundaries. A standalone table label can use the next
line as its value, but it cannot search arbitrarily forward through the file.

`parse_semantic_date` accepts ISO dates and named months. A slash date such as
03/04/2022 has two possible meanings and receives no selected value. A date such
as 13/03/2022 has one valid interpretation. Invalid calendar dates are retained
as unreadable mentions. The mortgage date, renewal date, maturity date, term
start, and offer expiry have distinct keys.

Rates expressed in basis points are converted to percentage points: 130 basis
points equals 1.30 percentage points. Monetary separators must have a supported
grouping shape. Ambiguous amounts are retained for review rather than changing
the principal's magnitude. OCR digit substitutions are flagged and cannot feed
a confirmed calculation until reviewed.

`resolve_semantic_facts` groups evidence by scope and field. Agreement resolves a
fact; different values produce a conflict. Page confidence can exclude a
candidate but is never used to silently win a disagreement. At a positive
confidence threshold, unknown OCR confidence cannot pass the threshold.

`apply_semantic_corrections` adds reviewer evidence. Earlier evidence remains in
the ledger with a superseded marker. A correction for `original.contract_rate`
does not change the renewal offer. Corrections do not imply lender certification.

## Mathematics and dates

`audit_rate_relationships` checks, within a single scope:

    posted rate - contract rate = contract discount

Inputs and output use percentage points. A 5.69% posted rate less a 4.39%
contract rate gives a 1.30 percentage-point discount. Decimal arithmetic avoids
binary rounding in the comparison. The tolerance is 0.005 percentage points,
and a negative calculated discount is a conflict.

A separate observation compares the original contract rate with the renewal
offer. Its difference is also reported in basis points. That difference is not
used as an IRD spread. Rate relationships with missing or conflicting inputs
have no calculated output.

`add_calendar_months` advances a calendar month count and clamps the day to the
destination month's last day. For example, January 31 plus one month becomes
February 28 or February 29. `audit_term_timelines` compares that calculated
term end with the stated maturity date and reports the signed difference in
days. A renewal term never borrows an original funding date as its start.

Term and amortization are compared only in the same scope. Term is the contract
duration; amortization is the repayment horizon. A shorter remaining
amortization prompts review rather than automatically invalidating the mortgage.

## Penalty wording

`extract_semantic_clauses` keeps separate evidence for mentions, negation,
conditions, and examples. A negated clause cannot waive unrelated discharge
fees. `audit_penalty_language` identifies missing payout inputs and requests the
lender's formula. It does not substitute a renewal rate for an IRD comparison
rate and does not publish a certified payout amount.

`reviewer_prompt_pack` turns conflicts, unreadable facts, and missing details
into evidence-linked review items. `create_document_semantic_audit` assembles
the ledger, checks, prompts, page metadata, and primary-source references.

`semantic_pdf_v16.py` reads searchable PDF text in memory and closes the PDF.
Image-only scans are rejected with an OCR request. The semantic audit consumes
the full bounded text, independently of the legacy extraction preview. The
frontend `semantic-audit.js` renders separate term groups, checks, and expandable
passages; every imported value is HTML-escaped.

## Primary references checked for this release

- [FCAC prepayment penalties](https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html): lender methods and comparison-rate selection vary.
- [FCAC terms and amortization](https://www.canada.ca/en/financial-consumer-agency/services/mortgages/mortgage-terms-amortization.html): contract duration and repayment horizon are distinct.
- [FCAC penalty disclosure guidance](https://www.canada.ca/en/financial-consumer-agency/services/industry/commissioner-guidance/guidance-9.html): calculation components and discount treatment require disclosure.

These are design references, not a lender-specific formula or endorsement.
V16 adds local rules and tests; it does not execute a new OCR model, copy an
external repository, or provide general-purpose legal language understanding.
