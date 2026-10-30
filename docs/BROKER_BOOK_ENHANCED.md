# Broker-book enhanced source release

Based on the supplied broker-book-review full ZIP, not the active checkout.
The original source ZIP and running collectors are unchanged.

## Functional additions

- Locale-aware CAD amounts, explicit percentage handling, bounded durations.
- Ambiguous numeric dates require a stated date order.
- Unknown/open mortgage types and conflicting dates block recommendations.
- Lender aliases match complete words; "Ltd" does not identify TD.
- Actual payment frequency and supplied payments drive balance projections.
- Original and statement balances/amortizations carry explicit bases.
- Stale, future, unlabelled, or invalid offers cannot silently become quotes.
- Original posted-rate evidence reaches applicable penalty calculations.
- A stated discount survives historical posted-rate lookup.
- Breaking later is compared on one end date without double-charging delay.
- Same-payment years saved is labelled a hypothetical lifetime-rate scenario.
- Imported fields can be edited and verified against their source document.
- OCR provenance, unresolved issues, and diagnostics survive review.
- CSV formula injection is neutralized; duplicate IDs are reported.
- Clearing or editing a book invalidates pending asynchronous replies.
- Review size, nested fields, upload options, and concurrency are bounded.
- Offline cache includes the editor; launcher recognizes versioned shells.

## Verification

The final test results are recorded after packaging in the delivery message.
Run python -m pytest -q -rs with PYTHONPATH=backend, and
node --test tests/*.test.mjs from the extracted project.
The source snapshot omits optional OCR binaries and the TD calculator fixture;
those integration checks skip explicitly when unavailable. Unit tests mock
OCR at the API boundary and do not establish real scan accuracy.

Release ZIPs are built with python tools/package_zip.py, which excludes test
output, local databases, locks, and external calculator fixtures.

## Limits

This is a tested local application, not a production certification or a lender
quote. Lender policies other than the verified TD method remain estimates.
Obtain a dated payout statement and written offer before acting. Future
posted rates, payment changes, variable-rate history, and eligibility cannot
be inferred from a current snapshot. Missing evidence produces a needs-data
result rather than fabricated savings.

The preview server was started with application lifespan disabled to avoid
starting additional rate collectors during UI verification. Its unrelated
live-market snapshot endpoint is therefore unavailable in that preview.
Normal startup initializes the market tracker. No live archive crawl or
user-process control was performed.
