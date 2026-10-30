# V5 Engineering Release Notes

- New official HTML collector with explicit per-source operator permission.
- Exact-host HTTPS allowlisting, no redirects, restricted response size/type.
- Runtime DNS checks for global-only addresses (additional deployment egress
  filtering is required to fully prevent DNS rebinding in production).
- Unique five-year posted-rate row validation; ambiguity fails closed.
- SHA-256 of response bytes and capture-time timestamp on archived observation.
- No inferred past posted rates, personalized lender offers, or claims that
  scraped rates reproduce a signed mortgage contract.
- CLI worker and 16 mock-network tests; no scheduled automated scraping.

## Release gates still open

The service is not a production-cleared financial-data collector. Before
running against a real bank, validate terms of use and robots, get necessary
permissions, add formal change monitoring and rate-source reviews, use outbound
network firewall controls, and test documented lender rate tables. Browser
end-to-end tests, current lender certifications, live account linking, and the
remaining 77,400-line platform are unfinished.
