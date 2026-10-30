# Renewal Radar roadmap

*John Khan · Alenza Fintech*

Three separate statuses, never merged:

- **Implemented**: the code exists.
- **Tested**: automated tests pass. Most use fictional or synthetic inputs.
- **Validated**: checked against real lender evidence (payout statements or the lender's own published calculator).

Passing tests prove the code does what we intended. They do not prove a lender charges that amount. Only TD is validated, and only against TD's own published calculator code, not against TD payout statements.

## Penalty engine and rates

| Item | Implemented | Tested | Validated |
|---|---|---|---|
| TD penalty method (term bands, months convention, half-up cents, long-term rule) | Yes | Yes | Against TD's published calculator code: 3,000/3,000 random cases, final charge exact to the cent (IRD and three-month parts executed from TD's file; the final-charge rule transcribed from TD's controller). Not yet against TD payout statements. |
| Other lenders' methods (RBC, BMO, Scotia, CIBC, National, monolines, credit unions) | Defaults | Yes | **No.** Labelled "estimate" until real statements pass the accuracy gate |
| Live posted rates: TD, CIBC, Scotiabank, BMO, Simplii (lender data feeds) | Yes | Parsers tested on recorded response shapes | Scotia 5-yr = BoC typical on 2026-10-14 (spot check) |
| Live posted rates: RBC, National, ATB, Desjardins, Tangerine (HTML) | Yes | Partly | Spot-checked against the BoC on 2026-10-14 |
| Bank of Canada / StatCan official series (5 years, weekly) | Yes | Yes | Official source |
| Five-year official rate dataset (BoC posted, actual new/outstanding rates insured/uninsured, bonds, prime, policy) | Yes (`dataset.py`) | Yes | Official source, complete weekly since Oct 2021 |
| Five-year lender-level history (bank-own feeds/pages via Common Crawl + Wayback) | Yes (resumable, single-instance, polite) | Yes | In progress; coverage and every gap in `data/ratewatch/history_coverage.json`. No third-party sites, no estimation |
| Live rates board, big banks + credit unions, primary + 3 backups | Yes (`live.py`, page "Live rates") | Yes (every tier forced in tests) | 23 of 26 lenders live on 2026-10-15; BMO via archive/BoC, Servus/Steinbach/Coast unavailable |
| Historical replay without hindsight (rates as of the calculation date) | Partly (`history.table_on`) | No | No |
| Untouched final-evaluation case set, separate from development cases | No | No | No |
| Lender/product accuracy report (errors, bias, sample sizes, exclusions) | TD oracle only (`backtest.py`) | Yes | TD calculator only |

## Decision helpers (`backend/renewal/ratewatch/extras.py`, `POST /api/ratewatch/extras/{tool}`)

| # | Item | Implemented | Tested | Validated | Safeguard |
|---|---|---|---|---|---|
| 1 | Break-even months | Yes | Yes | No | Includes fees |
| 2 | Cheapest day to break | Yes | Yes | No | Assumes today's posted rates hold |
| 3 | Blend-and-extend estimate | Yes | Yes | No | Weighted average; lenders may add a premium |
| 4 | Lump-sum-first saving | Yes | Yes | No | Only if the contract allows the privilege right before payout |
| 5 | Rate sensitivity (±0.25 / ±0.50) | Yes | Yes | No | Hypothetical moves |
| 6 | Port vs break | Yes | Yes | No | Simple; blended rate on new money is an input |
| 7 | Renewal countdown (120-day window) | Yes | Yes | No | Lender windows vary |
| 8 | Stress test (OSFI qualifying rate) | Yes | Yes | Rule is public | Not an approval |
| 9 | Net switching benefit | Yes | Yes | No | Same horizon; includes penalty and fees |
| 10 | CSV export | Yes | Yes | n/a | |
| 11 | Plain-text summary (EN/FR) | Yes | Yes | n/a | |
| 12 | French client letter (PDF) | Yes | Yes | n/a | Explains a calculation; does **not** interpret French contracts |
| + | Reverse-rate explorer | Yes | Yes | No | Returns **compatible ranges**, never a single "true" rate |
| + | Rate/date heatmap | Yes | Yes | No | Labelled HYPOTHETICAL; shows interest paid while waiting, since a lower penalty is not always a lower total cost |

## Review fixes

All fixed with a regression test each (`tests/test_ratewatch_review_fixes.py`): no charge at or after maturity; TD never
substitutes a different term rate; synthetic/duplicate cases cannot verify a lender (evidence required, held-out grading);
calibration cannot override TD's rules; Posted/Special columns read separately; `term_months` never rescaled; month-end
dates kept; forecast stops at the supplied maturity; amortization is an input; break-even and net-switch use one basis;
reverse-rate solved exactly; same-day source conflicts reported; failed downloads retried; PDFs built in memory and client
names kept out of URLs; release ZIP keeps dotfiles and excludes all databases; website calls the new endpoints
(Penalty page "Lender-exact check", new "Live rates" page).

## Second review

All 14 fixed with tests (`tests/test_ratewatch_review2.py`): no negative interest after repayment; variable/open/unknown
inputs rejected; past payouts use recorded rates, never today's; PDF text escaped; live validation fails closed; reverse-rate
returns every compatible interval; switching limited to the new offer's term; duplicate evidence detected numerically;
archived month units kept; empty discovery and parser-rejected captures retried; weekly backtest has no look-ahead; blank
accuracy tables load history; dates and rate tables validated; one live refresh at a time.

## Open gaps (not done)

1. Real-case evidence set: 100 payout statements linked to contracts and final amounts paid.
2. Payout-statement extraction validated on real documents (principal vs penalty vs accrued interest vs fees).
3. Multi-document case reconciliation (contract, renewal offer, payout statement, corrections).
4. Historical contract rules by lender, product and date; exact settlement conventions beyond TD.
5. Contract-specific prepayment planning (allowance amounts, reset dates, restrictions).
6. Combined-loan handling (HELOC segments, collateral charges).
7. Written-offer conditions (expiry, eligibility, fees).
8. Operational monitoring: scheduled collection, freshness checks, parser-breakage alerts (daily run + back-checks exist; scheduling and alert delivery do not).
9. Broker/client-management interface over the existing workspace foundations.
10. Production accounts, roles, tenant isolation, encrypted storage, secrets, privacy operations, hosting, backups, security assessment.
11. Independent financial review; full French interpretation and accessibility validation; real end-to-end acceptance testing.

## Later ideas

Contract flexibility comparison, broker opportunity dashboard, white-labelled reports, client collaboration, lawyer-ready evidence brief, debt-consolidation comparison, household stress testing, consent-based bank connection, optional private local language model (explanations only; calculations stay deterministic), mobile capture companion.
