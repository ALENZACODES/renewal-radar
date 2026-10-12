# Penalty engine v3: source-backed, versioned estimations

This extension prioritizes reproducible model output over unsupported claims of lender-exactness. Formulas vary by mortgage product, mortgage origination date, contractual rate discount, compounding and comparison term. Some bank pages give simplified examples; the payout statement remains authoritative.

## Methods

- `simple_differential`: specified comparison rate and existing contract rate; gross differential across remaining months.
- `posted_minus_discount`: rate differential between contract rate and current posted rate net of documented discount.
- `cibc_discount_addback`: illustrative CIBC contract branch for a larger three-month floor and IRD calculation. Specific contract wording must be confirmed; CIBC's official calculator is the reference.
- `present_value`: monthly amortizing streams, principal repayment and terminal loan value. A *transparent approximation*, not a reimplementation of the proprietary bank calculation.
- `undocumented`: refuses to invent a higher-of penalty; reports floor-only with evidence gaps.

## Missing evidence and certainty

- Unknown lenders and missing rate discounts: `floor_only`, no fabricated final penalty.
- Verified rate + documented inputs: `estimate` (never labelled legally binding).
- Open/matured mortgages: `no_charge_modelled` plus separately modelled fees.
- Historical rates must carry collection date, lender, product, term, source URL, content hash, eligibility flags and a human review status before use for original-discount rebuilding.
- Annual lump-sum privileges **cannot** automatically be deducted from a full payout. This requires positive contract eligibility evidence.

## REST endpoints

`GET /api/penalty/v3/lenders` and `POST /api/penalty/v3/estimate`

Sample body:

```json
{
  "balance": "400000",
  "annual_rate": "5",
  "remaining_months": 24,
  "lender": "td",
  "rate_type": "fixed",
  "comparison_posted_rate": "4",
  "documented_discount": "1",
  "discharge_fee": "350"
}
```

All money and rates are serialized as strings, not binary floating-point numbers. Rate units are percentage points.

## Sources for method validation

- RBC: https://www.rbcroyalbank.com/mortgages/understanding-mortgage-prepayment-charges.html
- RBC standard mortgage forms: https://www.rbcroyalbank.com/RBC%3AaYPyn8AU0lhTMGVe1kkb5QAAAJ0/legalforms/download/310102.pdf
- TD: https://apps.td.com/mortgage-prepayment-calculator/
- Scotia: https://www.scotiabank.com/content/dam/scotiabank/canada/en/documents/mortgages/What_you_need_to_know_Mortgages_and_Mortgage-Prepayment-Charges_1343814_1202_EN.pdf
- CIBC: https://www.cibc.com/en/personal-banking/mortgages/calculators/prepayment-calculator.html
- FCAC: https://www.canada.ca/en/financial-consumer-agency/services/mortgages/prepayment-penalty.html

**Validation gap:** Golden tests matching dated authenticated lender calculator statements across all applicable contract versions are still required before claiming lender-exact commercial calculations.

## Comparison-term rules and the date-driven workbench

`penalty/comparison.py` picks the IRD comparison rate from a table of published
terms (`{term_months: rate}`) with an explicit rule:

| Rule | Picks | Fails when |
|---|---|---|
| `nearest` | closest term, shorter on a tie | never (if the table has a rate) |
| `nearest_longer_on_tie` | closest term, longer on a tie | never |
| `round_down` | longest term not above the time left | time left is shorter than every term |
| `round_up` | shortest term not below the time left | time left is longer than every term |
| `interpolate` | straight line between neighbours | never; uses the edge rate outside the range rather than extrapolating |

`penalty/daycount.py` turns dates into contract month counts (`remaining_term`,
with part months rounded up, down or to nearest), gives actual-day three-month
interest, and pro-rates cash-back clawbacks.

`penalty/methods.py` records, per lender, the term rule, month rounding,
three-month basis and where the discount comes from (`contract`,
`original_posted` or `none`). Every spec is `verified: false` until it has been
checked against a payout statement, and the API says so.

`penalty/workbench.py` (`POST /api/penalty/v3/workbench`) takes dates, the
current posted table and the posted rate at funding, then runs the Decimal
engine and a sensitivity pass over every rule the table supports. If the rule
alone moves the estimate by $500 or more, the response warns about it. Missing
inputs are reported in `missing_fields`; nothing is filled in silently.
