# V17 Exit-Cost Timeline

The supplied reference image was used as a visual benchmark, not an authenticated
contract, rate feed or expected-value test. Its lender-specific IRD/PV numbers
cannot be reconstructed exactly without the underlying inputs and conventions.
The new interface replaces the dense mixed-purpose table with financial metrics,
an interactive dated curve, a month selector, explicit bucket transitions and
an expandable audit. The illustration is clearly fictional and can be replaced
with the current workspace without modifying its mortgage or document evidence.

## Calculation Walkthrough

`PenaltyTimelineRequest` validates principal, rates, whole months, dates, fees,
payment frequency, method and term buckets. It rejects nonfinite numbers,
duplicate buckets, unexpected fields and projections longer than 120 months.

`month_date` computes anniversaries from the original start date. January 31
becomes February 28 or 29 and then March 31, not March 28. These are scenario
dates, not daily settlement-interest calculations.

`simulate` is the existing payment engine. For a fixed Canadian nominal rate j
and f payments per year, the periodic rate is:

    r = (1 + j / 2)^(2 / f) - 1

For principal P and n payment periods, the ordinary scheduled payment is:

    A = P r / (1 - (1 + r)^(-n))

Zero-rate and accelerated-frequency branches stay in the existing tested engine.
At each anniversary the timeline uses the ledger balance after scheduled payments
that have elapsed. It does not assume additional lump sums or privilege deductions.

`select_bucket` uses either the shortest entered term at least as long as the
remaining term, or the nearest term with longer terms winning a tie. This is an
explicit modelling convention, not a universal Canadian lender rule. An absent
matching bucket yields missing evidence, not a substitute market rate. Comparison
rates are a static entered snapshot; the application does not forecast future rates.

Each point calls the existing `calculate_penalty` with updated balance and months.
The quarter-year three-month-interest proxy is:

    three = balance x annual rate / 100 x 0.25

The simple differential proxy is:

    IRD = balance x max(contract rate - comparison rate, 0) / 100
          x remaining months / 12

The posted-discount branch first subtracts the documented original discount from
the comparison posted rate. Missing discount or method evidence keeps final IRD
and total penalty unknown. The present-value branch uses the existing illustrative
monthly-compounding cash-flow/terminal-balance model. It is not lender-exact and
is distinct from the Canadian scheduled-payment compounding above.

For a modelled closed fixed mortgage with sufficient evidence:

    core charge = max(three, IRD)
    total estimate = core charge + separately entered fees

Variable-rate, matured and fully repaid pathways retain their existing limitations.
The graph shows core charge, floor and IRD separately; entered fees appear outside
the graph and in the dated table. A final charge of zero at modelled maturity does
not remove discharge or other fees. Unknown charges are null gaps, not zeroes.

## Interpretation

The selected month updates its principal, term bucket, charge, method, missing
fields and formulas. It does not identify the economically optimal refinance date.
Comparing dates also requires carrying interest, payment cash flows, future rates,
new lender fees, underwriting and the actual dated payout statement.

Primary consumer and lender references checked for these limits:

- https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html
- https://www.rbcroyalbank.com/mortgages/understanding-mortgage-prepayment-charges.html

The new 26 backend tests cover ledger balances, month ends, bucket boundaries,
rate transitions, missing evidence, PV/fee separation, maturity, validation and API
behaviour. Frontend tests cover null gaps, input conversion, scenario selection,
sample labelling, compatibility with existing reports, escaping and actual bundled
ECharts rendering. Screenshot and phone-size checks are recorded in the release
sidecar, not treated as mathematical validation of lender-exact calculations.
