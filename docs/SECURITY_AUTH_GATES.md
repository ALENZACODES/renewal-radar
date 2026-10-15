# API access gates (PR security-data-gates)

## Public allowlist (no credential)

| Path | Reason |
|---|---|
| `GET /api/health/live` | Liveness probe |
| `GET /api/health/ready` | Readiness probe |
| `GET /`, `/service-worker.js`, `/robots.txt` | Frontend shell |
| `/assets/*`, `/js/*` | Static assets |
| `/docs`, `/redoc`, `/openapi.json` | OpenAPI UI **non-production only** |

## Capability URLs (token in path)

| Path | Reason |
|---|---|
| `GET /api/shares/{share_token}` | Share link is the credential |
| `GET /shared/{token}` | Shared UI shell |

## Process-wide gate

- Dependency: `renewal.security.access.require_api_access`
- Header: `X-Api-Key`
- Secret: `RR_API_ACCESS_KEY` (min 24 characters)
- `APP_ENV=production`: missing/short key → **503**; wrong/missing header → **401**
- Development: open unless `RR_API_ACCESS_KEY` is set

## Resource tokens (existing, still required where declared)

| Header | Used for |
|---|---|
| `X-Broker-Token` | Broker workspace tenancy |
| `X-Case-Token` | Case read/update/share |
| `X-OCR-Review-Token` | OCR review sessions |
| `X-Rate-Ingest-Key` | Rate observation ingest (`RR_RATE_INGEST_KEY`) |

## Gaps still open (not solved by this gate alone)

See the inventory comment on the PR / agent report: lead POST by workspace id,
banklink sandbox without end-user identity, OCR session create, demo workspace
creation flag, and any broker route that trusts `wid` without re-checking token
on every branch.

## Leads tenancy (batch 2)

- Canonical create: `POST /api/v5/broker/workspaces/{wid}/leads` + `X-Broker-Token`.
- Legacy `POST /api/v5/leads` still requires the broker token and only uses body `workspace_id` after membership checks (temporary until callers move).
- `created_by` is set server-side to the workspace id (audit `lead_created`); client `id` / `status` / `created_by` / `workspace_id` are dropped.
- DELETE loads the lead row, takes `workspace_id` from DB, authorizes via withdraw token or broker token for that workspace, audits `lead_withdrawn`, returns **404** on failure.
- Principal today = broker workspace token (no OIDC yet).

## Case tokens (broker-first, no Auth0)

- `POST /api/cases` requires `X-Broker-Token` + body `workspace_id`. Returns **case id only** (no long-lived access token).
- `POST /api/cases/{id}/tokens` (broker of owning workspace) mints a scoped token: allowlisted scopes, TTL, rate limit, SHA-256 hash at rest. Plaintext returned once.
- Allowed scopes: `case:read`, `case:write`, `case:share`, `banklink:connect`, `banklink:read`.
- API-key-only callers cannot mint case tokens.
- **TODO:** email OTP verification before handing a borrower invite token (email send not in repo).

## Bank-link binding + PKCE

- Consents bind to `case_id` + `workspace_id` (broker or `banklink:connect` case token).
- Session requires case token `banklink:connect` + PKCE S256 `code_challenge`; optional HttpOnly `rr_banklink_nonce` cookie.
- `POST /api/v5/banklink/complete` is **public** (no `X-Api-Key`): one-time `state` + `code_verifier` + optional cookie. Atomic state claim.
- Provider handles sealed with Fernet when `RR_BANKLINK_KEY` is set; otherwise plaintext sandbox stub (**TODO:** fail closed in production).
- Mortgages: same-workspace broker **or** case token `banklink:read` / `banklink:connect`.
- Revoke is idempotent and deletes consent/link/state bindings.

## Remaining gaps

- Case / banklink token stores are in-process (need shared store for multi-instance).
- Email OTP for borrower invites (stubbed TODO).
- No OIDC yet — broker workspace token is the principal.
- `RR_BANKLINK_KEY` optional in sandbox; should be required in production.

## OCR intake + CSV export (this chunk)

- Central upload helper `renewal.security.uploads`: stream-capped ~15 MB, PDF/PNG/JPEG magic sniff, PDF page limit, image pixel budget.
- OCR temp dirs via `renewal.ocr.tempfiles.ocr_tempdir` + stale `rr-*` sweep.
- Log redaction filter (`renewal.security.log_redact`) masks SIN-shaped and account-like digit runs; OCR dump patterns redacted. Do not log raw OCR text.
- CI installs `tesseract-ocr` (+ eng/fra). `requires_tesseract` **fails** when `CI=true` and Tesseract is missing; skips locally.
- Ratewatch `csv_safe` prefixes cells starting with `= + - @ \\t \\r` with `'` before CSV write.

## Next PR — Ratewatch quarantine (not in this chunk)

Remaining Ratewatch work deferred (no DB migrations in this PR):

- Persist collector quarantine events with retention/TTL and broker-visible audit.
- Harden live scrape/backfill failure quarantine (source URL review queue).
- Shared/multi-instance case + banklink token stores (currently in-process).
- Production fail-closed for `RR_BANKLINK_KEY` and borrower email OTP invites.
