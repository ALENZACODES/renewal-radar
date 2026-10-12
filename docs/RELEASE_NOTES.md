# Renewal Radar 2.0 — release notes

**Package type:** Working full-stack MVP / hackathon demo, not an independently audited bank-grade commercial deployment.

## Shipped
- Nine-screen responsive browser UI with light/dark modes and local sample data.
- Six-frequency Canadian mortgage math, term-aligned comparison, fees/credits, principal reconciliation, prepayment and rate paths.
- Conditional OSFI/Finance Canada 2026 mortgage switching policy classifier.
- ReportLab 3-page financial strategy PDF and downloadable event calendar.
- Page-linked PDF extraction with manual confirmation, optional Nebius missing-field suggestions.
- An eight-step tool-backed agent sequence with optional Nemotron explanation.
- Bank of Canada official data API, conservative official Big Six posted-rate HTML check, optional Tavily official URL discovery, idempotent rate-ingest worker.
- Negotiation call and email generator.
- SQLite workspace cases, random private access keys and expiring/revocable read-only shares.
- FastAPI automatic OpenAPI reference and validation, Docker Compose, tests and documented security controls.

## Not shipped / requires external configuration
- Hosted public URL, commercial bank-specific quotes/lead integrations, full public-user authentication and encrypted multi-tenant storage.
- An OCR cloud service for scanned image-only PDFs, automated full bank-rate coverage, real Nebius/Tavily API credentials.
- iOS/Android applications, licensed broker handoff, lender prequalification or approved mortgage offers.
- Independently validated WCAG/browser render across all devices.
- The aspirational approximately 50,000+ lines of enterprise functionality described in the product master blueprint. The implementation is a smaller functional MVP, not 1,000 pages of certified production code.

## Test evidence
- 62 Python tests passed.
- 6 Node template/format tests passed.
- Three-page sample PDF rendered and manually inspected.
- Manual browser acceptance checklist supplied for checks that still need a real browser.

No GitHub publishing, contest registration/submission, production deployment or paid API actions were performed.
