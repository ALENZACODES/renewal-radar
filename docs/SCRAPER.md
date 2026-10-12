# Posted-rate scraper

`backend/renewal/scraper/` reads public lender rate pages once a day and turns
them into posted-rate observations for the rate history.

## Politeness rules

- robots.txt is read before every host (cached for a day). If it can't be read,
  is malformed, or the URL isn't `https://`, the lender is skipped
  (`skipped_robots`).
- One request per lender per day. A second run the same day skips lenders that
  already succeeded (`skipped_today`).
- At least 10 seconds between requests, longer if robots.txt sets `Crawl-delay`.
- Identifying user agent with a contact URL (`RR_SCRAPER_CONTACT`). No cookies,
  logins, form posts or rate-limit evasion.
- Responses are capped at 5 MB.

## Parsing

`parse.py` reads table rows and card blocks first, then falls back to text near
a term label. Rules that matter for penalties:

- a column headed "posted" wins over other rate columns;
- rows labelled special, promo, limited-time or discount are skipped;
- variable rows written as `Prime + 0.10% = 4.55%` give the effective rate,
  never the spread;
- only 1, 2, 3, 4, 5, 7 and 10-year fixed, 5-year variable and prime are kept;
- scripts, styles and templates are removed first.

Every rate keeps the text it was read from (`evidence`). The parser reproduces
the archived RBC capture of 2015-05-06 exactly (see
`tests/fixtures/scraper/rbc_archive_2015-05-06.html`).

## After each run

`runner.assess` checks each lender's 5-year fixed rate against the Bank of
Canada posted 5-year rate. Within 0.60 points the capture is `posted_ok`;
otherwise `likely_special_offer`, which keeps it out of penalty math. Any term
that moved 0.50 points or more since the previous run gets an alert, because
that usually means the page layout changed.

## Running

```bash
PYTHONPATH=backend python -m renewal.scraper.runner --out data/current            # static HTML
PYTHONPATH=backend python -m renewal.scraper.runner --out data/current --browser  # needs playwright
```

Output: `data/current/YYYY-MM-DD.json` (status, rates, evidence, quality, alerts)
and `data/current/history.csv` (`date,lender,term,rate_pct,quality`), which the
rate pipeline reads as `scraper_history.csv`.
