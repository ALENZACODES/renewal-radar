# Commercial deployment / security release gate

This application has working business calculations but **is not approved for production collection of identifying mortgage/household information**. Before a real customer launch, complete and document the following controls.

1. Identity and authorization: supported OIDC/Clerk login, MFA for broker/admin accounts, per-tenant object authorization with real owner identifiers, revoke and rotate sessions, CSRF review.
2. Database and files: managed PostgreSQL, encrypted database disks, application-level encryption for identifiers, separate object store with per-object permissions, managed KMS secrets and rotation, secure deletion and retention policies.
3. Intake: malware and PDF exploit sandbox in isolated worker container, secure scanning OCR where permitted, password-protected PDFs handled carefully, max-page and byte-size policy, no personal info in logs.
4. Canadian privacy and marketing: PIPEDA consent, access/deletion procedures, breach response, CASL for opted-in notices, source-of-truth financial terms, legal/professional licensing review for broker handoff and referral compensation disclosures.
5. Financial QA: signed versioned rule database and policy effective-date review, formal qualification tests on insured/uninsured/refinance types, independent mortgage mathematics validation, lender-specific IRD data and quote comparison controls.
6. Bank website partnerships: official API or licensed feed preferred; confirm robots/terms, bank-specific selectors with parser contracts, 2-person manual source verification, regional/insurance/product conditions, per-source last-check times and outage alerts.
7. Rate controls: feature-flag unverified rates, forbid them from recommendation rank, expire stale observations, compare explicit quote provenance, maintain change logs.
8. Infrastructure: WAF, TLS, request quotas, per-user API metering, rate limiting on PDF and external-model calls, abuse and prompt-injection evaluation, dependency/SBOM scans, backups and disaster recovery.
9. Model safety: logging without confidential input content, explicit model version and confidence, optional redaction, consent to AI processing and cross-border data flows, independent deterministic finance/rules tools.
10. Accessibility and observability: WCAG 2.2 AA audit, EN/FR terminology review, 390px/keyboard/screen reader end-to-end testing, Sentry/OpenTelemetry, canary deployments, penetration test, incident runbook.

Currently included: bounded PDF size/page validation; no uploaded PDF byte storage; constrained field extraction; server-only AI keys; strict mortgage schemas; fail-closed quote parsing; expiring bearer-token shares; no-referrer/CSP/nosniff headers; financial tests. These are **not substitutes** for the commercial controls above.
