# Five-year posted-rate history: month-by-month audit

Window 2021-10 to 2026-10 (61 months) for the six big banks. Every month has exactly one value and one of three labels:

- **bank-own**: the bank's own published rate, from an archived copy of its page or data feed (or our live reading), accepted only if its 5-year rate is within 0.75 points of the Bank of Canada big-six figure that week.
- **bridged**: no copy that month, but the bank's own 5-year rate is identical in the nearest months on both sides (at most 6 months apart) and the Bank of Canada figure did not move in between.
- **Bank of Canada fill**: no bank-own copy survives; the Bank of Canada's weekly big-six typical posted rate (1, 3 and 5-year) is shown, labelled, and never used as the bank's current rate.

Full detail (every term, links, explanations): `data/ratewatch/history_audit.csv`.

## Summary

| Bank | Bank-own | Bridged | Bank of Canada fill | Total |
|---|---|---|---|---|
| RBC | 12 | 5 | 44 | 61 |
| TD | 3 | 0 | 58 | 61 |
| Scotiabank | 30 | 3 | 28 | 61 |
| BMO | 52 | 8 | 1 | 61 |
| CIBC | 18 | 11 | 32 | 61 |
| National Bank | 21 | 5 | 35 | 61 |

Bank-own months checked against the Bank of Canada: 136; exact match 70; average gap 0.07 points; 90% within 0.20.

Why the Bank of Canada fill is a fair stand-in: TD's own published daily history (1999-2018) equals it in 87% of 1,034 weeks (average gap 0.02 points). The series is built from the six big banks' posted rates.

## RBC

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-10-27 |
| 2021-11 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20211129232404/https://www.rbcroyalbank.com/mortgages/mortgage-rates.html) |
| 2021-12 | bridged | 4.79 | 4.79 | RBC own readings 2021-11 and 2022-01; Bank of Canada V80691335 flat at 4.79% between them |
| 2022-01 | bank-own | 4.79 | 4.79 | [archive copy](https://arquivo.pt/wayback/20220126180855/https://www.rbcroyalbank.com/mortgages/mortgage-rates.html) |
| 2022-02 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20220205102106/https://www.rbcroyalbank.com/mortgages/mortgage-rates.html) |
| 2022-03 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20220309061734/https://www.rbcroyalbank.com/mortgages/mortgage-rates.html) |
| 2022-04 | bank-own | 4.79 | 4.99 | [archive copy](https://web.archive.org/web/20220425150938/https://www.rbcroyalbank.com/mortgages/mortgage-rates.html) |
| 2022-05 | Bank of Canada fill | 5.39 | 5.39 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-05-25 |
| 2022-06 | Bank of Canada fill | 6.04 | 6.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-06-29 |
| 2022-07 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-07-27 |
| 2022-08 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-08-31 |
| 2022-09 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-09-28 |
| 2022-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-10-26 |
| 2022-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-11-30 |
| 2022-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-12-28 |
| 2023-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-01-25 |
| 2023-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-02-22 |
| 2023-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-03-29 |
| 2023-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-04-26 |
| 2023-05 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-05-31 |
| 2023-06 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-06-28 |
| 2023-07 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-07-26 |
| 2023-08 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-08-30 |
| 2023-09 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-09-27 |
| 2023-10 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-10-25 |
| 2023-11 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-11-29 |
| 2023-12 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-12-27 |
| 2024-01 | Bank of Canada fill | 6.89 | 6.89 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-01-31 |
| 2024-02 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-02-28 |
| 2024-03 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-03-27 |
| 2024-04 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-04-24 |
| 2024-05 | bank-own | 6.79 | 6.84 | Common Crawl capture 20240518232944 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2024-06 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-06-26 |
| 2024-07 | Bank of Canada fill | 6.79 | 6.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-07-31 |
| 2024-08 | Bank of Canada fill | 6.59 | 6.59 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-08-28 |
| 2024-09 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-09-25 |
| 2024-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-10-30 |
| 2024-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-11-27 |
| 2024-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-12-25 |
| 2025-01 | bank-own | 6.39 | 6.49 | Common Crawl capture 20250115031234 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2025-02 | bank-own | 6.39 | 6.49 | Common Crawl capture 20250206133603 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2025-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-03-26 |
| 2025-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-04-30 |
| 2025-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-05-28 |
| 2025-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-06-25 |
| 2025-07 | bank-own | 6.09 | 6.09 | Common Crawl capture 20250707232744 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2025-08 | bridged | 6.09 | 6.09 | RBC own readings 2025-07 and 2025-09; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-09 | bank-own | 6.09 | 6.09 | Common Crawl capture 20250918002213 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2025-10 | bridged | 6.09 | 6.09 | RBC own readings 2025-09 and 2026-01; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-11 | bridged | 6.09 | 6.09 | RBC own readings 2025-09 and 2026-01; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-12 | bridged | 6.09 | 6.09 | RBC own readings 2025-09 and 2026-01; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-01 | bank-own | 6.09 | 6.09 | Common Crawl capture 20260120095821 of https://www.rbcroyalbank.com/mortgages/mortgage-rates.html |
| 2026-02 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-02-25 |
| 2026-03 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-03-25 |
| 2026-04 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-04-29 |
| 2026-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-05-27 |
| 2026-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-06-24 |
| 2026-07 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-07-29 |
| 2026-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-08-26 |
| 2026-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-09-30 |
| 2026-10 | bank-own | 6.19 | 6.19 | [archive copy](https://www.rbcroyalbank.com/mortgages/mortgage-rates.html (live reading stored 2026-10-14)) |

## TD

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-10-27 |
| 2021-11 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-11-24 |
| 2021-12 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-12-29 |
| 2022-01 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-01-26 |
| 2022-02 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-02-23 |
| 2022-03 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-03-30 |
| 2022-04 | Bank of Canada fill | 4.99 | 4.99 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-04-27 |
| 2022-05 | Bank of Canada fill | 5.39 | 5.39 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-05-25 |
| 2022-06 | Bank of Canada fill | 6.04 | 6.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-06-29 |
| 2022-07 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-07-27 |
| 2022-08 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-08-31 |
| 2022-09 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-09-28 |
| 2022-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-10-26 |
| 2022-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-11-30 |
| 2022-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-12-28 |
| 2023-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-01-25 |
| 2023-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-02-22 |
| 2023-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-03-29 |
| 2023-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-04-26 |
| 2023-05 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-05-31 |
| 2023-06 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-06-28 |
| 2023-07 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-07-26 |
| 2023-08 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-08-30 |
| 2023-09 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-09-27 |
| 2023-10 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-10-25 |
| 2023-11 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-11-29 |
| 2023-12 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-12-27 |
| 2024-01 | Bank of Canada fill | 6.89 | 6.89 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-01-31 |
| 2024-02 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-02-28 |
| 2024-03 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-03-27 |
| 2024-04 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-04-24 |
| 2024-05 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-05-29 |
| 2024-06 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-06-26 |
| 2024-07 | Bank of Canada fill | 6.79 | 6.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-07-31 |
| 2024-08 | Bank of Canada fill | 6.59 | 6.59 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-08-28 |
| 2024-09 | bank-own | 6.79 | 6.49 | [archive copy](https://web.archive.org/web/20240919153735/https://ix0.apps.td.com/api/get-rates/en) |
| 2024-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-10-30 |
| 2024-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-11-27 |
| 2024-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-12-25 |
| 2025-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-01-29 |
| 2025-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-02-26 |
| 2025-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-03-26 |
| 2025-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-04-30 |
| 2025-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-05-28 |
| 2025-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-06-25 |
| 2025-07 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-07-30 |
| 2025-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-08-27 |
| 2025-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-09-24 |
| 2025-10 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-10-29 |
| 2025-11 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-11-26 |
| 2025-12 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-12-31 |
| 2026-01 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-01-28 |
| 2026-02 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-02-25 |
| 2026-03 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-03-25 |
| 2026-04 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-04-29 |
| 2026-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-05-27 |
| 2026-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-06-24 |
| 2026-07 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260728164104/https://ix0.apps.td.com/api/get-rates/en) |
| 2026-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-08-26 |
| 2026-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-09-30 |
| 2026-10 | bank-own | 6.09 | 6.19 | [archive copy](https://ix0.apps.td.com/api/get-rates/en (live reading stored 2026-10-14)) |

## Scotiabank

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | bank-own | 4.79 | 4.79 | [archive copy](https://arquivo.pt/wayback/20211027132905/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2021-11 | bridged | 4.79 | 4.79 | Scotiabank own readings 2021-10 and 2022-02; Bank of Canada V80691335 flat at 4.79% between them |
| 2021-12 | bridged | 4.79 | 4.79 | Scotiabank own readings 2021-10 and 2022-02; Bank of Canada V80691335 flat at 4.79% between them |
| 2022-01 | bridged | 4.79 | 4.79 | Scotiabank own readings 2021-10 and 2022-02; Bank of Canada V80691335 flat at 4.79% between them |
| 2022-02 | bank-own | 4.79 | 4.79 | [archive copy](https://arquivo.pt/wayback/20220226220028/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-03 | bank-own | 4.99 | 4.79 | [archive copy](https://arquivo.pt/wayback/20220331210822/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-04 | bank-own | 4.99 | 4.99 | [archive copy](https://arquivo.pt/wayback/20220430212744/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-05 | bank-own | 5.39 | 5.39 | [archive copy](https://arquivo.pt/wayback/20220528214506/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-06 | bank-own | 5.84 | 6.04 | [archive copy](https://arquivo.pt/wayback/20220625053936/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-07 | bank-own | 5.99 | 6.04 | [archive copy](https://arquivo.pt/wayback/20220726130142/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-08 | bank-own | 5.99 | 6.14 | [archive copy](https://arquivo.pt/wayback/20220825074151/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-09 | bank-own | 6.14 | 6.14 | [archive copy](https://arquivo.pt/wayback/20220930211738/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-10 | bank-own | 6.14 | 6.49 | [archive copy](https://arquivo.pt/wayback/20221029202556/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-11 | bank-own | 6.14 | 6.49 | [archive copy](https://arquivo.pt/wayback/20221130205955/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2022-12 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20221231204342/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-01 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230131205429/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-02 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230228205754/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-03 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230331202802/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-04 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230429204219/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-05 | bank-own | 6.34 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230531210433/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-06 | bank-own | 6.44 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230630232130/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-07 | bank-own | 6.54 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230729010158/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-08 | bank-own | 6.84 | 6.84 | [archive copy](https://arquivo.pt/wayback/20230831194740/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-09 | bank-own | 6.84 | 6.84 | [archive copy](https://arquivo.pt/wayback/20230930200343/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-10 | bank-own | 7.04 | 7.04 | [archive copy](https://arquivo.pt/wayback/20231031211638/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-11 | bank-own | 7.04 | 7.04 | [archive copy](https://arquivo.pt/wayback/20231129212308/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2023-12 | bank-own | 7.04 | 7.04 | [archive copy](https://arquivo.pt/wayback/20231230201925/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-01 | bank-own | 6.79 | 6.89 | [archive copy](https://arquivo.pt/wayback/20240131210556/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-02 | bank-own | 6.79 | 6.84 | [archive copy](https://arquivo.pt/wayback/20240229212042/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-03 | bank-own | 6.79 | 6.84 | [archive copy](https://arquivo.pt/wayback/20240329210636/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-04 | bank-own | 6.79 | 6.84 | [archive copy](https://arquivo.pt/wayback/20240425195415/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-05 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-05-29 |
| 2024-06 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-06-26 |
| 2024-07 | Bank of Canada fill | 6.79 | 6.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-07-31 |
| 2024-08 | bank-own | 6.59 | 6.59 | [archive copy](https://arquivo.pt/wayback/20240823093247/https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage) |
| 2024-09 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-09-25 |
| 2024-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-10-30 |
| 2024-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-11-27 |
| 2024-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-12-25 |
| 2025-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-01-29 |
| 2025-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-02-26 |
| 2025-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-03-26 |
| 2025-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-04-30 |
| 2025-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-05-28 |
| 2025-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-06-25 |
| 2025-07 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-07-30 |
| 2025-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-08-27 |
| 2025-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-09-24 |
| 2025-10 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-10-29 |
| 2025-11 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-11-26 |
| 2025-12 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-12-31 |
| 2026-01 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-01-28 |
| 2026-02 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-02-25 |
| 2026-03 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-03-25 |
| 2026-04 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-04-29 |
| 2026-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-05-27 |
| 2026-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-06-24 |
| 2026-07 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-07-29 |
| 2026-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-08-26 |
| 2026-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-09-30 |
| 2026-10 | bank-own | 6.19 | 6.19 | [archive copy](https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage (live reading stored 2026-10-15)) |

## BMO

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20211031131900/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1634914292945) |
| 2021-11 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20211126073932/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2021-12 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20211227223505/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-01 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20220131195545/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-02 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20220228225800/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-03 | bank-own | 4.79 | 4.79 | [archive copy](https://web.archive.org/web/20220331041859/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-04 | bank-own | 4.99 | 4.99 | [archive copy](https://web.archive.org/web/20220430055132/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-05 | bank-own | 5.39 | 5.39 | [archive copy](https://web.archive.org/web/20220529143054/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-06 | bank-own | 6.04 | 6.04 | [archive copy](https://web.archive.org/web/20220625103332/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-07 | bank-own | 6.14 | 6.14 | [archive copy](https://web.archive.org/web/20220731030909/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-08 | bank-own | 6.14 | 6.14 | [archive copy](https://web.archive.org/web/20220830205333/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?_=1514618633636) |
| 2022-09 | bank-own | 6.14 | 6.14 | [archive copy](https://web.archive.org/web/20220926223723/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-10 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20221026030957/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-11 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20221130065037/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2022-12 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20221230064154/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-01 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230131172436/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-02 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230221200956/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-03 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230322102402/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-04 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230425205826/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1677009350314) |
| 2023-05 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230520200147/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-06 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230630061034/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-07 | bank-own | 6.64 | 6.49 | [archive copy](https://web.archive.org/web/20230712144750/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-08 | bank-own | 6.79 | 6.79 | [archive copy](https://web.archive.org/web/20230819093751/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?_=1518872725278) |
| 2023-09 | bank-own | 6.89 | 6.84 | [archive copy](https://web.archive.org/web/20230913201043/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-10 | bank-own | 7.09 | 7.04 | [archive copy](https://web.archive.org/web/20231008035602/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2023-11 | bridged | 7.09 | 7.04 | BMO own readings 2023-10 and 2023-12; Bank of Canada V80691335 flat at 7.04% between them |
| 2023-12 | bank-own | 7.09 | 7.04 | [archive copy](https://arquivo.pt/wayback/20231201055508/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-01 | bank-own | 6.89 | 6.89 | [archive copy](https://web.archive.org/web/20240131030329/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-02 | bank-own | 6.89 | 6.89 | [archive copy](https://web.archive.org/web/20240201141052/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-03 | bank-own | 7.04 | 6.84 | [archive copy](https://web.archive.org/web/20240331213430/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?_=1519447893836) |
| 2024-04 | bridged | 7.04 | 6.84 | BMO own readings 2024-03 and 2024-05; Bank of Canada V80691335 flat at 6.84% between them |
| 2024-05 | bank-own | 7.04 | 6.84 | [archive copy](https://web.archive.org/web/20240520212856/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?_=1519447895264) |
| 2024-06 | bank-own | 7.04 | 6.84 | [archive copy](https://web.archive.org/web/20240604024354/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-07 | bank-own | 6.79 | 6.79 | [archive copy](https://web.archive.org/web/20240708082237/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-08 | bank-own | 6.79 | 6.59 | [archive copy](https://arquivo.pt/wayback/20240829000511/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-09 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-09-25 |
| 2024-10 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20241009130556/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2024-11 | bridged | 6.49 | 6.49 | BMO own readings 2024-10 and 2024-12; Bank of Canada V80691335 flat at 6.49% between them |
| 2024-12 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20241208205116/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-01 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20250123180836/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-02 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20250225151341/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-03 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20250309190212/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-04 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20250429100336/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-05 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20250516131516/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-06 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20250609094243/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-07 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20250715153042/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-08 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20250827105513/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1677009350314) |
| 2025-09 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20250929091608/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2025-10 | bridged | 6.09 | 6.09 | BMO own readings 2025-09 and 2025-11; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-11 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20251121055730/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1677009343968) |
| 2025-12 | bridged | 6.09 | 6.09 | BMO own readings 2025-11 and 2026-01; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-01 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260116122708/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2026-02 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260226195647/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1677009350314) |
| 2026-03 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260304042300/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?_=1519447904149) |
| 2026-04 | bridged | 6.09 | 6.09 | BMO own readings 2026-03 and 2026-05; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-05 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260501023533/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2026-06 | bridged | 6.09 | 6.09 | BMO own readings 2026-05 and 2026-07; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-07 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260720055828/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2026-08 | bridged | 6.09 | 6.09 | BMO own readings 2026-07 and 2026-09; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-09 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20260930/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp) |
| 2026-10 | bank-own | 6.09 | 6.09 | [archive copy](https://web.archive.org/web/20261005063932/https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp?v=1677009343968) |

## CIBC

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-10-27 |
| 2021-11 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-11-24 |
| 2021-12 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-12-29 |
| 2022-01 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-01-26 |
| 2022-02 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-02-23 |
| 2022-03 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-03-30 |
| 2022-04 | bank-own | 4.99 | 4.79 | [archive copy](https://web.archive.org/web/20220418171700/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2022-05 | Bank of Canada fill | 5.39 | 5.39 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-05-25 |
| 2022-06 | Bank of Canada fill | 6.04 | 6.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-06-29 |
| 2022-07 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-07-27 |
| 2022-08 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-08-31 |
| 2022-09 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-09-28 |
| 2022-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-10-26 |
| 2022-11 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20221101211817/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2022-12 | bridged | 6.49 | 6.49 | CIBC own readings 2022-11 and 2023-03; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-01 | bridged | 6.49 | 6.49 | CIBC own readings 2022-11 and 2023-03; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-02 | bridged | 6.49 | 6.49 | CIBC own readings 2022-11 and 2023-03; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-03 | bank-own | 6.49 | 6.49 | [archive copy](https://web.archive.org/web/20230303212846/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2023-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-04-26 |
| 2023-05 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-05-31 |
| 2023-06 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-06-28 |
| 2023-07 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-07-26 |
| 2023-08 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-08-30 |
| 2023-09 | bank-own | 6.79 | 6.84 | [archive copy](https://web.archive.org/web/20230905232911/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2023-10 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-10-25 |
| 2023-11 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-11-29 |
| 2023-12 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-12-27 |
| 2024-01 | Bank of Canada fill | 6.89 | 6.89 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-01-31 |
| 2024-02 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-02-28 |
| 2024-03 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-03-27 |
| 2024-04 | bank-own | 6.84 | 6.84 | [archive copy](https://web.archive.org/web/20240416014307/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=5YRVARCLO%2c) |
| 2024-05 | bank-own | 6.84 | 6.84 | [archive copy](https://web.archive.org/web/20240530030219/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=5YRVARCLO%2c) |
| 2024-06 | bank-own | 6.84 | 6.84 | [archive copy](https://web.archive.org/web/20240605025908/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2024-07 | bank-own | 6.84 | 6.79 | [archive copy](https://web.archive.org/web/20240717030504/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2024-08 | Bank of Canada fill | 6.59 | 6.59 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-08-28 |
| 2024-09 | bank-own | 6.84 | 6.59 | [archive copy](https://web.archive.org/web/20240910214011/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2C5YRVARCLO%2C) |
| 2024-10 | bank-own | 6.84 | 6.49 | [archive copy](https://web.archive.org/web/20241009153121/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2024-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-11-27 |
| 2024-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-12-25 |
| 2025-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-01-29 |
| 2025-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-02-26 |
| 2025-03 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-03-26 |
| 2025-04 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-04-30 |
| 2025-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-05-28 |
| 2025-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-06-25 |
| 2025-07 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20250711201300/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2025-08 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20250810012413/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2025-09 | bridged | 6.49 | 6.09 | CIBC own readings 2025-08 and 2025-11; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-10 | bridged | 6.49 | 6.09 | CIBC own readings 2025-08 and 2025-11; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-11 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20251125174210/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2C5YRVARCLO%2CMICRO%2C) |
| 2025-12 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20251219171455/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2C5YRVARCLO%2CMICRO%2C) |
| 2026-01 | bridged | 6.49 | 6.09 | CIBC own readings 2025-12 and 2026-04; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-02 | bridged | 6.49 | 6.09 | CIBC own readings 2025-12 and 2026-04; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-03 | bridged | 6.49 | 6.09 | CIBC own readings 2025-12 and 2026-04; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-04 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20260404152405/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2C5YRVARCLO%2CCCM%2C) |
| 2026-05 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20260528173803/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2c) |
| 2026-06 | bridged | 6.49 | 6.09 | CIBC own readings 2026-05 and 2026-09; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-07 | bridged | 6.49 | 6.09 | CIBC own readings 2026-05 and 2026-09; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-08 | bridged | 6.49 | 6.09 | CIBC own readings 2026-05 and 2026-09; Bank of Canada V80691335 flat at 6.09% between them |
| 2026-09 | bank-own | 6.49 | 6.09 | [archive copy](https://web.archive.org/web/20260930172651/https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=1&sourceProductCode=PRIME%2c) |
| 2026-10 | bank-own | 6.49 | 6.19 | [archive copy](https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy (live reading stored 2026-10-14)) |

## National Bank

| Month | Status | 5-yr | BoC 5-yr | Evidence |
|---|---|---|---|---|
| 2021-10 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-10-27 |
| 2021-11 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-11-24 |
| 2021-12 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2021-12-29 |
| 2022-01 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-01-26 |
| 2022-02 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-02-23 |
| 2022-03 | Bank of Canada fill | 4.79 | 4.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-03-30 |
| 2022-04 | Bank of Canada fill | 4.99 | 4.99 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-04-27 |
| 2022-05 | Bank of Canada fill | 5.39 | 5.39 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-05-25 |
| 2022-06 | Bank of Canada fill | 6.04 | 6.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-06-29 |
| 2022-07 | Bank of Canada fill | 6.14 | 6.14 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-07-27 |
| 2022-08 | bank-own | 6.18 | 6.14 | [archive copy](https://arquivo.pt/wayback/20220805153924/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2022-09 | bridged | 6.18 | 6.14 | National Bank own readings 2022-08 and 2022-10; Bank of Canada V80691335 flat at 6.14% between them |
| 2022-10 | bank-own | 6.18 | 6.14 | [archive copy](https://arquivo.pt/wayback/20221017085318/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2022-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-11-30 |
| 2022-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2022-12-28 |
| 2023-01 | bank-own | 6.53 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230124223355/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2023-02 | bridged | 6.53 | 6.49 | National Bank own readings 2023-01 and 2023-04; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-03 | bridged | 6.53 | 6.49 | National Bank own readings 2023-01 and 2023-04; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-04 | bank-own | 6.53 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230418190646/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2023-05 | bridged | 6.53 | 6.49 | National Bank own readings 2023-04 and 2023-06; Bank of Canada V80691335 flat at 6.49% between them |
| 2023-06 | bank-own | 6.53 | 6.49 | Common Crawl capture 20230601045627 of https://www.nbc.ca/personal/mortgages/rates.html |
| 2023-07 | bank-own | 6.53 | 6.49 | [archive copy](https://arquivo.pt/wayback/20230724184644/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2023-08 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-08-30 |
| 2023-09 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-09-27 |
| 2023-10 | bank-own | 7.08 | 7.04 | [archive copy](https://arquivo.pt/wayback/20231020211621/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2023-11 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-11-29 |
| 2023-12 | Bank of Canada fill | 7.04 | 7.04 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2023-12-27 |
| 2024-01 | bank-own | 7.47 | 6.89 | [archive copy](https://arquivo.pt/wayback/20240127145810/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2024-02 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-02-28 |
| 2024-03 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-03-27 |
| 2024-04 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-04-24 |
| 2024-05 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-05-29 |
| 2024-06 | Bank of Canada fill | 6.84 | 6.84 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-06-26 |
| 2024-07 | Bank of Canada fill | 6.79 | 6.79 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-07-31 |
| 2024-08 | bank-own | 6.88 | 6.79 | [archive copy](https://arquivo.pt/wayback/20240812020554/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2024-09 | bank-own | 6.63 | 6.59 | Common Crawl capture 20240910233401 of https://www.nbc.ca/personal/mortgages/rates.html |
| 2024-10 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-10-30 |
| 2024-11 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-11-27 |
| 2024-12 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2024-12-25 |
| 2025-01 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-01-29 |
| 2025-02 | Bank of Canada fill | 6.49 | 6.49 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2025-02-26 |
| 2025-03 | bank-own | 6.43 | 6.49 | [archive copy](https://arquivo.pt/wayback/20250317013651/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-04 | bank-own | 6.33 | 6.49 | [archive copy](https://arquivo.pt/wayback/20250430215408/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-05 | bank-own | 6.13 | 6.09 | [archive copy](https://arquivo.pt/wayback/20250531190646/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-06 | bank-own | 6.13 | 6.09 | [archive copy](https://arquivo.pt/wayback/20250630191214/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-07 | bank-own | 6.13 | 6.09 | [archive copy](https://arquivo.pt/wayback/20250731165031/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-08 | bank-own | 6.13 | 6.09 | [archive copy](https://arquivo.pt/wayback/20250831171818/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2025-09 | bank-own | 6.13 | 6.09 | Common Crawl capture 20250916130943 of https://www.nbc.ca/personal/mortgages/rates.html |
| 2025-10 | bridged | 6.13 | 6.09 | National Bank own readings 2025-09 and 2025-11; Bank of Canada V80691335 flat at 6.09% between them |
| 2025-11 | bank-own | 6.13 | 6.09 | Common Crawl capture 20251112014620 of https://www.nbc.ca/personal/mortgages/rates.html |
| 2025-12 | bank-own | 6.13 | 6.09 | [archive copy](https://arquivo.pt/wayback/20251216224120/https://www.nbc.ca/personal/mortgages/rates.html) |
| 2026-01 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-01-28 |
| 2026-02 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-02-25 |
| 2026-03 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-03-25 |
| 2026-04 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-04-29 |
| 2026-05 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-05-27 |
| 2026-06 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-06-24 |
| 2026-07 | bank-own | 6.13 | 6.09 | Common Crawl capture 20260722164515 of https://www.nbc.ca/personal/mortgages/rates.html |
| 2026-08 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-08-26 |
| 2026-09 | Bank of Canada fill | 6.09 | 6.09 | Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of 2026-09-30 |
| 2026-10 | bank-own | 6.18 | 6.19 | [archive copy](https://www.nbc.ca/personal/mortgages/rates.html (live reading stored 2026-10-14)) |
