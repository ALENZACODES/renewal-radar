# Ratewatch: live lender rates, exact penalties, backtests

Module: `backend/renewal/ratewatch/`. Data: `data/ratewatch/`. All sources are free and need no keys.

| Command (run from `backend/`) | What it does |
|---|---|
| `python -m renewal.ratewatch.run daily` | Scrape every source, auto-repair moved pages, run back-checks |
| `python -m renewal.ratewatch.backfill` | Five-year history from the Wayback Machine (resumable, polite pace) |
| `python -m renewal.ratewatch.backtest` | TD oracle + rate-history checks -> `data/ratewatch/backtest_report.json` |
| `python -m renewal.ratewatch.letter` | Sample one-page penalty assessment PDF |
| `python -m renewal.ratewatch.loanbook download` | OSFI mortgage book sizes for every regulated lender |
| `python -m renewal.ratewatch.ontario` | Verify the 100 Ontario lenders |
| `python -m renewal.ratewatch.live` | Refresh the live rates board (big banks + credit unions) |
| `python -m renewal.ratewatch.dataset` | Rebuild the 5-year rate dataset (`rates_5yr.csv`, `big6_posted_5yr.csv`) |
| `python tools/package_zip.py` | Build and check the release ZIP |

## Live rates board (`live.py`, web page "Live rates")

6 big banks and 20 credit unions. For each lender, sources are tried in order until one passes validation:

| Order | Source |
|---|---|
| Primary | The lender's own data feed or rates page |
| Backup 1 | A second live source from the lender (French page, alternate feed), else automatic rediscovery of its moved page |
| Backup 2 | The last good reading (up to 14 days old, shown with its age) |
| Backup 3 | The newest web-archive copy of the lender's own source (Wayback, then Common Crawl) |

Validation: banks' 5-year posted must sit within 0.75 of the Bank of Canada big-six figure; credit-union rates must sit
in a plausible band above the 5-year bond; a "special" above "posted" is rejected. If everything fails, a big bank shows
the Bank of Canada big-six figure marked "not lender-specific"; a credit union shows "Unavailable". No rate is estimated.

API (server running): `GET /api/ratewatch/live`, `POST /api/ratewatch/live/refresh`, `GET /api/ratewatch/rates/{lender}`, `POST /api/ratewatch/penalty`,
`POST /api/ratewatch/forecast`, `POST /api/ratewatch/letter`, `GET /api/ratewatch/backtest`.

## Lender data feeds

| Lender | Feed |
|---|---|
| TD | `psservice.td.com/ca/en/carate/getRates` (POST): posted, discount, special per term |
| CIBC | `cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy`: type 1 posted, 18 special |
| Scotiabank | `dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage`: posted per term |
| BMO | `bmo.com/public-data/api/epm/v1.0/bmo-epm-mortgage.json` (posted), `.../v2.0/bmo-ca-mortgages-rates.json` (specials) |
| Simplii | `online.simplii.com/ebm-pno/api/v2/json/rates/ALL` (posted) + CIBC specials |
| RBC, National Bank, ATB, Desjardins, Tangerine | HTML tables (`parse.py`) |
| Bank of Canada / StatCan | Valet `CHARTERED_BANK_INTEREST`, `A4_RATES_MORTGAGES`; StatCan vector 80691335 |

## Backtest: TD's own code as the answer key

TD publishes its prepayment-charge maths as browser JavaScript. `tools/td_oracle.mjs` runs that file
unmodified in Node; `backtest.py` feeds 2,000 random mortgages to it and to our engine.
Run `python tools/fetch_td_oracle.py` first (TD's files are downloaded locally, not stored in git).

TD rules found in its code: comparison term by months left (0-8.99 -> 6-month, 9-17.99 -> 1-yr, 18-29.99 -> 2-yr,
30-41.99 -> 3-yr, 42-53.99 -> 4-yr, 54-65.99 -> 5-yr, 66-77.99 -> 6-yr, 78-101.99 -> 7-yr, 102+ -> 10-yr);
months left = whole months + (days + 1)/31; IRD = amount x (contract - (posted - discount)) x months / 12;
three months' interest = amount x rate / 4; cents rounded half-up.

Other lenders stay labelled **estimate** until real payout statements in `data/ratewatch/penalty_cases.csv`
pass `python -m renewal.ratewatch.run accuracy` (10+ cases, 99% within 1%).

## Lender-exact penalties: five banks checked against their own calculator code

Each bank's public calculator code is downloaded (never committed) and run in Node as the answer key. Random mortgages go
through both that code and `ird.py`, and the results must agree to the cent.

| Bank | Calculator code | Fetch | Oracle | Backtest | Result |
|---|---|---|---|---|---|
| TD | td-prepayment.min.js | `tools/fetch_td_oracle.py` | `tools/td_oracle.mjs` | `backtest.td_oracle` | 3000/3000 |
| Scotiabank | dmts.scotiabank.com prepayment main.js (logic.js) + termRates.json | `tools/fetch_scotia_oracle.py` | `tools/scotia_oracle.mjs` | `backtest.scotia_oracle` | 3000/3000 |
| CIBC | mortgageprepayment.min.js (cibc_rules) | `tools/fetch_cibc_oracle.py` | `tools/cibc_oracle.mjs` | `backtest.cibc_oracle` | 3000/3000 |
| BMO | prepayment-calculator app bundle (y() and the pay-in-full charge) | `tools/fetch_bmo_oracle.py` | `tools/bmo_oracle.mjs` | `backtest.bmo_oracle` | 3000/3000 |
| National Bank | nbc.ca/forms/financing/prepayment-charges-calculator (fixed, full payout script) | `tools/fetch_nbc_oracle.py` | `tools/nbc_oracle.mjs` | `backtest.nbc_oracle` | 3000/3000 |

Rules found in each bank's code:
- **Scotiabank:** whole months remaining; term bands from termRates.json; comparison is posted minus discount; no charge if the comparison rate is 3 or more points above the contract rate; terms of 84+ months with 60+ months elapsed are charged 3 months' interest.
- **CIBC:** remaining days × 12 / 365; posted-term limits 12/18/30/42/54/78/102/120 months. The IRD is interest payable at (contract + discount) minus interest payable at posted, payment by payment over the remaining payments, rounded to the cent each step. Three months' interest is at (contract + discount), compounded semi-annually. Every charge is capped at the interest left to maturity, and under 3 months remaining the charge is the interest to maturity.
- **BMO:** calendar months remaining. Exactly on a term boundary (9, 18, 30, 42, 54, 66, 78, 102 months) it takes the higher of the two posted rates; a 6-year (72-month) term is used. Charge = max(IRD, 3 months); with 1–2 months left it is prorated to that many thirds.
- **National Bank:** whole months remaining. The comparison is NBC's posted rate for the remaining term with **no discount add-back**, plus one month's interest capped at $500.

Caveats:
- National Bank's form asks the user for the posted rate, so our term choice (nearest posted term) is an assumption. The formula itself is exact.
- CIBC's IRD needs the regular payment. Pass `Mortgage(payment=...)`; otherwise it is computed from the balance, rate and amortization.

The Interest Act s.10 cap for individuals (terms over 5 years, more than 5 years elapsed) is still applied for CIBC, BMO and National Bank, even though their calculators do not model it.

Equitable Bank's own page (equitablebank.ca/mortgage-rates) is now backup 1 for EQ Bank on the live board, read by `scrape.equitable_rows`.
It takes only the Standard posted table and skips reverse-mortgage and APR rows.

## Five-year history: every month covered, every value labelled

`python -m renewal.ratewatch.backfill --fill` rebuilds coverage. It makes no network calls and is safe while the backfill runs.
The backfill also runs it at the end of every pass. Each bank-month gets exactly one of three labels:

1. **Bank-own:** the bank's own page or feed, from the live scraper, Wayback, Common Crawl or **Arquivo.pt**. The 5-year rate must sit within 0.75 of the Bank of Canada figure for that week.
2. **Bridged:** the bank's own 5-year posted rate is identical at the nearest readings on both sides of the gap, those readings are at most 6 months apart, and the Bank of Canada figure did not move at all between them. The earlier full bank-own table is carried across the gap.
3. **Bank of Canada typical:** the Bank of Canada's weekly big-six typical posted 1, 3 and 5-year rates (series V80691333/4/5) for the last week of the month. These are labelled "not this bank's own figure".

Why the Bank of Canada fallback is defensible:
- TD's own published daily history (1999–2018) equals this figure in 896 of 1,034 weeks (87%), with an average gap of 0.02 points.
- Across the 60 months where we hold both a bank-own reading and the Bank of Canada figure (RBC, Scotiabank, National Bank), the average gap is 0.08 points and 90% of months are within 0.20.

Guarantees:
- Fills are stored under the bank's id with `how = bridged | boc_typical`. Anything presented as a current rate uses `history.table_on(..., own_only=True)` and never sees them: the book review's current tables, CLI payouts, validation, accuracy evidence, and the bank-own dataset weeks.
- Where a fill is used for a past date, the answer says so. The book review marks the deal as an estimate and asks for the commitment letter. Historical API tables carry the fill label.
- Refilling first deletes every earlier fill, so a month that later gains a bank-own reading drops its fill.
- In `rates_5yr.csv`, filled rows are a separate series (`bank_posted_gap_fill`) with the label in the source column.
- Bank of Canada fills cover the 1, 3 and 5-year terms only. A past IRD that needs another term from a filled month returns "needs data", never a guess.

Coverage on 2026-10-15 (61 months, Oct 2021–Oct 2026), as bank-own + bridged + Bank of Canada:

| Bank | Bank-own | Bridged | Bank of Canada | Total |
|---|---|---|---|---|
| RBC | 12 | 5 | 44 | 61 |
| TD | 1 | 0 | 60 | 61 |
| Scotiabank | 30 | 3 | 28 | 61 |
| BMO | 1 | 0 | 60 | 61 |
| CIBC | 1 | 0 | 60 | 61 |
| National Bank | 21 | 5 | 35 | 61 |

`coverage_grade` is A (every month has a labelled source). `grade` stays the strict bank-own grade (D: TD, BMO and CIBC).

Why TD, BMO and CIBC have so few bank-own months: their rate pages load the numbers after the page opens, and their data feeds are not held by any public archive inside the window. Archives checked: Wayback, Common Crawl, Arquivo.pt, archive.today (CAPTCHA, and only about 5 copies), Archive-It/Library and Archives Canada, Library of Congress, Iceland and Australia. Their bank-own share now grows one month at a time from the live scraper's daily readings.

## Daily recording from now on (`ratewatch/recorder.py`)

Windows task **"Renewal Radar daily rates"** (installed by `tools/install_recorder_task.ps1`, removed with `-Remove`).
It runs `tools/record_daily.cmd` at 08:15, 12:45 and 18:30 every day, plus 5 minutes after logon.
Each run records every lender's own posted rates for the day. Five layers stop one failure from losing a day:

1. **Retry with backoff.** A lender not recorded on the first try is retried after 30 s, 2 min and 5 min. The timeout grows to 40 s and then 60 s, so a slow site still counts.
2. **Second source.** Each lender's backup feed (for example TD's calculator feed, BMO's rate include `json_mortgage_include.jsp`, Equitable's own page). Without a backup, its rates page is rediscovered on the lender's own site.
3. **Self-repair.** If both fail, the lender's site is searched again for its rates page, so a moved URL fixes itself. Whatever it finds is validated before saving.
4. **Redundant schedule.** Three runs a day plus logon. A missed run starts as soon as the PC is on and online. The task restarts up to 3 times on failure. Lenders already recorded that day are skipped, so extra runs cost nothing.
5. **Watchdog and safe defaults.** Nothing is ever invented. A lender with no reading keeps its last good reading on the board, and the month stays covered by the labelled gap fill. After 3 days in a row without a reading, `data/ratewatch/ALERTS.txt` names the lender.

Every run also refreshes the Bank of Canada series (stored figures are used if it is unreachable) and the monthly gap fills.
Only validated readings are saved, from the lender's own live sources, never from archives.

The recorder holds the live board's lock only while it fetches, never during retry waits, so the board and the API stay usable.

Files:
- Logs: `data/ratewatch/recorder_logs/YYYY-MM.log`.
- Health per lender: `data/ratewatch/recorder_health.json`.
- Run by hand at any time: `tools\record_daily.cmd`.

Expected misses: most B lenders and private lenders publish no rates, so they always show "Unavailable". That is not a fault.

### Blocked sites (added 2026-10-17)

On 2026-10-16, bmo.com and coastcapitalsavings.com began refusing this machine: they accept the connection and never reply. Every other bank answered in under half a second. That is a block on their side, and it is never routed around.
- **Cool-down.** Once a lender's site fails to answer, the recorder leaves it alone for the rest of the run: no retries, no self-repair crawl, about one request per run instead of 10 or more. A temporary block can then expire instead of being renewed.
- **Layer 6, fresh archive copy.** Without contacting the lender, the recorder looks for a public-archive capture of the lender's own page or feed from the last 3 days. It records that under the capture date, labelled `wayback`. This is the lender's own published rates, collected by the archive.
- **System-curl fallback.** If the Python client is dropped but the site is otherwise reachable, the same GET is retried with the operating system's curl over IPv4.

### Manual readings (`how = manual`)

When a lender's bot protection rejects automated clients but its public page opens normally in a browser, a person can read it once. On 2026-10-17 that happened for BMO and Coast Capital: python and curl were refused, while a normal browser on the same PC opened both sites. The page is read in a visible browser and recorded with `how = manual`. The page content is kept in `data/ratewatch/manual/` as evidence, and the reading passes the same Bank of Canada check.

Manual readings count as the lender's own data. The recorder never automates a browser to get past a lender's bot protection.

Coast Capital's mortgage rates are on `/rates/mortgages`; `/rates` lists only GIC, prime and foreign-exchange rates. Its posted table, the one it uses for term-break penalties, is identified by the heading above it (`scrape.coast_rows`).


## RBC (added 2026-10-18)

RBC's calculator runs on RBC's server (`prepayment-charge-calculator.cgi`), so it cannot be executed locally the way the other five banks' code is.
Instead, `tools/rbc_oracle.py` submits cases to it politely (one case every 15 seconds). The 34 answers recorded on 2026-10-18 are kept in `tests/fixtures/rbc_calculator_2026-10-18.json`, and `backtest.rbc_cases()` checks the engine against them offline.

What RBC's calculator does, reconstructed from those answers:
- **Remaining term:** actual days × 12 / 365, rounded **up** to a tenth of a month. RBC labels each tenth as 3 days, so "48 months 3 days" means 48.1 months. All 34 labels match.
- **Comparison term:** the posted term nearest the remaining term, with ties going up (18 months uses the 2-year rate, 30 months the 3-year).
- **Three months' interest:** balance × monthly rate (semi-annual compounding) × 3 × 30.42 / (365/12). The payment and the date of the last payment have no effect.
- **IRD:** the present value of (contract − comparison) interest on the declining balance. Regular payments run at the contract rate, each month is discounted at the comparison monthly rate, and the leftover tenth-of-a-month is charged on the final balance.
- **Charge:** the greater of the two. The Interest Act cap still applies for terms over 5 years.

Result: all 34 cases are within $0.30 (worst $0.29 on $6,694, under 0.005%). 12 are exact to the cent, including every three-month and whole-month case.
RBC itself calls its calculator an estimate; the payout statement is final.

## Smaller lenders' own rate pages (added 2026-10-18; `ratewatch/small_lenders.py`)

Found by searching the lenders' own sites. Every source below is the lender's own page, data feed or PDF, read without a login.

| Lender | Source | Kind |
|---|---|---|
| Servus | servus.ca/rates (mortgage tab `div.catSection[data-catid=3]`, below the GIC tab) | posted + special |
| Community Trust | communitytrust.com/mortgage-rates/ (sideways term/rate table) | posted |
| Questbank | communitytrust.com/questbank/mortgage-rates/ (same template) | posted |
| Effort Trust | efforttrust.com/trust-banking-mortgage-rates.php | posted |
| KEB Hana Bank | hanabank.ca/pb/pu/pbpu008s01 (inline `pbpuJsonObj` JSON, "Posted Rate") | posted |
| CMLS | cmls.ca residential rates (inline `var MortgageRates`, option-code map) | offered |
| RFA Bank | rfa.ca/prime ("Standard Rates", insured column) | offered |
| WealthONE | broker rate-sheet PDF (two columns paired by position) | offered (base) |
| Bridgewater | bwbbrokerinfo.ca/mortgage-rates (best credit tier, 1-3 yr) | offered |
| Bloom Finance | api.bloomfin.ca/api/rates (reverse mortgage) | offered |
| Antrim | lending guidelines (private 1st, lowest LTV, 1-yr open) | offered |
| Atrium MIC | residential products (1st, 1-yr) | offered |
| Hillmount | broker FAQ ("prime plus 2.50%") + current prime | offered |

Lenders that publish no machine-readable rates are listed in `small_lenders.NOT_PUBLIC` with the reason. They show "Not published" on the board and are never fetched:
- **Blocked by bot protection:** Home Trust, MCAN, HomeEquity Bank.
- **Broker-only:** Haventree, Fisgard, CMI, Brightpath, Neighbourhood.
- **Not published, or a range/example only:** Merix, Firm Capital, Alpine, Fairstone.

Cameron Stephens and Trez Capital were removed: both are now commercial-only lenders.

B and private lenders that quote only 1-3 year terms are validated against their longest term instead of a 5-year rate. Banks and credit unions still need a 5-year rate.

## Smaller lenders' own calculators (added 2026-10-18)

Three more lenders publish penalty calculators that run in the browser. Each one is now reproduced exactly: 3,000 random cases per lender against its own unmodified code, all equal to the cent. To fetch the files, run `tools/fetch_small_lender_oracles.py`; they are never committed.

| Lender | Code run | Harness | Rule (from its code) |
|---|---|---|---|
| Desjardins | `calculateur-indemnites-calculs.js` | `tools/desjardins_oracle.mjs` | gap = contract - (posted for nearest term - discount), floored at 0; IRD = gap x balance / 365 x days; 3 months = balance x rate / 4 (daily under 30 days) |
| Tangerine | `mortgagePrePayment-calculator` clientlib, run in a minimal fake page | `tools/tangerine_oracle.mjs` | compares with Tangerine's current rate for the remaining-term bucket; simple-interest IRD over years + months; 7- and 10-year terms pay three months near the end |
| Simplii | `calculator.js` + `pcf_rules.js` (CIBC family) | `tools/simplii_oracle.mjs` | payment-by-payment IRD at (contract + discount) vs posted; terms under 18 months move to the 2-year rate; +0.15% on short terms; interest to maturity under 3 months |

Five more lenders bundle their penalty code inside web apps: ATB (Vue), Haventree, Laurentian and Equitable (Next.js / Turbopack), and Bridgewater (Angular). Each bundle is loaded into Node through a minimal module loader, or its calculation is cut out verbatim. 3,000 random cases per lender, all equal to the cent. To fetch the files, run `tools/fetch_web_app_oracles.py`; it finds the hashed chunk by the calculator's own code, and the files are never committed.

| Lender | Code run | Harness | Rule (from its code) |
|---|---|---|---|
| ATB | `mpp-calculator.app.js` module 8844 + vendors bundle, fake Vue | `tools/atb_oracle.mjs` | 30/360 days remaining; nearest posted term (incl. 2.5 yr) by days, ties to the higher rate; IRD = balance x days x (contract - (posted - original discount)) / 360; no discount for terms started before 2020 |
| Haventree | Turbopack chunk, fake React `useCallback` | `tools/haventree_oracle.mjs` | whole months; IRD = (rate - reinvestment rate for the band) x balance x months / 12; bands 1-17 / 18-29 / 30-41 / 42+ months |
| Laurentian | Next.js submit handler cut verbatim | `tools/laurentian_oracle.mjs` | months = floor(days/30) - 1; IRD = balance x months x (posted at signing - reference rate) / 12 + one month's interest capped at $500; 3 months on the posted rate |
| Equitable | Turbopack helper module 1759 + charge function cut verbatim | `tools/equitable_oracle.mjs` | compares with a Government of Canada yield: 1-year T-bill under 2 years, else the 2/3/5-year bond; simple IRD over calendar months |
| Bridgewater | `bwb-module.js` IRD class cut verbatim | `tools/bridgewater_oracle.mjs` | months = days x 12/365; GoC 1-5 year bond + 0.75% premium (0.50% before Apr 2011); 20% annual allowance deducted first |

### Comparison rates that are not posted mortgage rates

Four of these lenders measure the penalty against something other than their posted rates. `ratewatch/comparison.py` supplies exactly that, and never borrows a posted table in its place:

- **Equitable:** Bank of Canada 1-year T-bill (`TB.CDN.1Y.MID`) and 2/3/5-year benchmark bonds, stored by `history.official()` (5 years deep).
- **Bridgewater:** the bond feed its own calculator loads (`ama.ab.ca/api/bondrate/current`), saved by the daily recorder as `BWB_BONDS`.
- **Haventree:** the reinvestment table on its calculator page, saved daily as `HAVENTREE_REINVEST`.
- **Laurentian:** its reference rates load from its CMS at runtime and are not published in a readable form. A Laurentian fixed-rate review stops at "needs data" with the three-month floor.

B2B Bank is its own lender (ALT18), not a Laurentian alias.
