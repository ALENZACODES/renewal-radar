# V12 Contract Intelligence Concept

## What This Layer Is

The V12 contract-intelligence layer is a deterministic reasoning layer over a
mortgage document that has already been read by OCR and V11 document
understanding.

It does four things:

1. Turns extracted document facts into evidence nodes.
2. Links related facts with evidence edges.
3. Scores practical review risks.
4. Answers user questions only from evidence it can point to.

This is different from a generic chatbot. It does not free-write legal opinions.
It says what it found, where it found it, how the math was checked, what still
needs a human, and which questions should go back to the lender.

## The Core Idea

A mortgage contract is not just text. It is a set of related facts:

- A balance has a date.
- A rate may be current, contract, posted or offered.
- A contract discount only makes sense relative to a posted rate and contract
  rate from the same product/date.
- A term should line up with a mortgage start date and maturity date.
- A payment amount only makes sense with frequency, rate and amortization.
- IRD language only becomes financially meaningful with a written payout
  statement and lender comparison rate.

V12 represents those facts as a graph:

```text
field:posted_rate ----feeds----> calculation:contract_discount
field:contract_rate --feeds----> calculation:contract_discount
field:term_months ----checked--> check:mortgage_date_term_maturity_sequence
clause:interest_rate_differential --context--> lender question: payout statement
```

That graph gives every conclusion a trail. If the app says “contract discount
needs review,” the response includes evidence IDs that lead back to the field or
check that caused the warning.

## Why Not Just Ask An LLM?

Contract review is high-stakes. A fluent answer that cannot show evidence is
not good enough.

The V12 design uses deterministic rules first:

- Regex and normalized field extraction identify mortgage-specific values.
- Canadian mortgage math checks rate, payment, term and discount relationships.
- Clause detectors find risk language such as IRD, prepayment, automatic renewal
  or property-tax collection.
- Evidence IDs connect every answer to a field, clause, check or calculation.

An LLM could be added later as a summarizer, but it should summarize the graph,
not replace the graph.

## Public GitHub Ecosystem Used As Design Input

No external code is copied into V12. The project uses these public sources as
architecture references:

- **Docling**: structure-aware document intelligence, layout, OCR and table
  options. This supports the idea that contracts should be parsed into structure
  instead of flat text.
- **Unstructured**: document partitioning into elements. This influenced the
  field/clause/check/evidence-node split.
- **Microsoft Presidio**: privacy boundary design. This influenced the choice to
  redact evidence snippets and avoid raw OCR persistence.
- **CUAD**: expert-labeled contract review dataset. This influenced the idea
  that contract intelligence should be clause-grounded and evidence-grounded.
- **LEGAL-BERT / Contracts-BERT**: legal-domain model family. This is a future
  optional classifier direction, not a runtime dependency.
- **LayoutParser**: document image analysis toolkit. This influenced the future
  direction for visual evidence boxes and layout-aware review.

The runnable V12 package remains local and dependency-light. Optional adapters
can be added later, but the deterministic rule layer must continue to work
without them.

## Mortgage-Specific Reasoning

V12 focuses on Canadian mortgage documents rather than generic commercial
contracts.

It understands the following relationships:

### Contract Rate

The contract rate is the interest rate written into the mortgage contract. It is
not necessarily the posted rate and not necessarily the new renewal offer.

### Posted Rate And Contract Discount

If the document shows:

```text
posted rate = 5.69%
contract rate = 4.39%
contract discount = 1.30%
```

V12 checks:

```text
posted rate - contract rate = implied discount
5.69 - 4.39 = 1.30
```

If the document discount does not match the implied discount, V12 marks that as
a review risk.

### Term, Start Date And Maturity Date

If a document shows a mortgage start date and a maturity date, V12 computes the
months between those dates and compares it with the stated term.

Example:

```text
Mortgage start date: 2022-03-01
Maturity date:       2027-03-01
Term:                60 months
```

The dates imply 60 months, so the timeline check passes.

### Amortization

Amortization is the repayment schedule. It is different from term.

A document can show:

```text
Term: 60 months
Remaining amortization: 240 months
```

That is normal. The rate and key contract terms are fixed for 60 months, while
the payment schedule is based on 240 months.

### Payment Estimate

For fixed Canadian mortgage rates, the app uses nominal annual rates compounded
semi-annually, then converts to the payment frequency.

That lets V12 compare an observed payment to a simple estimate. A mismatch does
not prove the OCR is wrong. It may mean the payment includes property taxes,
insurance, different rounding or a different frequency.

### Interest Rate Differential

IRD language is detected but not treated as a binding payout calculation.

V12 asks:

- Which comparison rate is used?
- Which comparison date is used?
- Is the penalty the greater of IRD and three-month interest?
- Does the contract discount affect the calculation?
- Is there a written payout statement?

The lender payout statement controls the actual penalty.

## What The API Returns

The contract-intelligence result includes:

- `evidence_graph`: fields, clauses, checks, calculations, sections and links.
- `risk_assessment`: scored risks with evidence IDs and suggested actions.
- `readiness`: whether the document is ready for mortgage comparison prefill.
- `lender_questions`: practical questions to ask the lender.
- `answer`: optional deterministic answer to a user question.

## Safety Boundaries

The layer does not:

- certify contract terms;
- replace a broker, lawyer or lender;
- calculate a binding IRD payout;
- store raw OCR text;
- guarantee every identifier has been redacted;
- rely on a network model or hidden dependency.

The intended workflow is:

1. OCR reads the document.
2. V10 extracts fields.
3. V11 understands mortgage terms and checks the math.
4. V12 builds evidence and risk reasoning.
5. A human verifies the source document before using the result.
