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
