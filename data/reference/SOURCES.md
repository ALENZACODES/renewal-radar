# Reference posted-rate data

| File | Content | Range | Source and licence |
|---|---|---|---|
| `boc_V80691333.csv` | Chartered-bank conventional 1-year posted rate, weekly | 1980 to 2026-10-07 | Bank of Canada Valet, free reuse with attribution (https://www.bankofcanada.ca/terms/) |
| `boc_V80691334.csv` | 3-year, weekly | 1980 to 2026-10-07 | Bank of Canada Valet |
| `boc_V80691335.csv` | 5-year, weekly; the posted rate used in qualifying and in many IRD contracts | 1975 to 2026-10-07 | Bank of Canada Valet |
| `boc_V80691311.csv` | Prime rate, weekly | 1975 to 2026-10-07 | Bank of Canada Valet |
| `34100145.csv` | Monthly 5-year conventional rate (v733833) | 1951-01 to 2026-08 | Statistics Canada table 34-10-0145, Open Government Licence - Canada |
| `lender_posted_rates_wayback_validated.csv` | Per-lender rates parsed from Internet Archive captures of lender rate pages | RBC 2011+, BMO 2015 to 2019, TD 2019+ | Internet Archive captures of public pages |
| `scraper_history.csv` | Daily output of the rate scraper | 2026-10-11+ | Public lender rate pages |

## Quality rules

`renewal.rates.validate.classify` re-checks every lender capture: if the capture's
5-year fixed rate is within 0.60 percentage points of the Bank of Canada posted
5-year rate for that week (reference no older than 45 days), every term on the
capture is `posted_ok`. Otherwise it is `likely_special_offer`, or `unverified`
when the capture has no 5-year rate. Only `official` and `posted_ok` rows are
used for penalty math. Where a lender has no usable row, the chartered-bank
series is returned with `proxy: true`.

Not included: Ratehub and WOWA histories (their terms forbid redistribution), and
any proprietary penalty-calculator data.

Rebuild the tidy history:

```bash
PYTHONPATH=backend python -m renewal.rates.pipeline data/reference build/rates
```
