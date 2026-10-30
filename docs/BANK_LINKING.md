# Bank linking

**Rule:** Renewal Radar never asks for, receives or stores online-banking
passwords. Bank-app agreements at RBC, TD, BMO, Scotiabank and CIBC forbid
sharing credentials, and the Consumer-Driven Banking framework exists to replace
screen scraping with token-based consent. Every request body is checked for
credential-like keys (`password`, `pin`, `username`, `otp`, `mfa_code` and so
on) at any depth, and is refused if one is present.

## Approved providers

| Provider | How the user connects | Mortgage data available | Status here |
|---|---|---|---|
| Plaid (Canada) | Plaid Link (provider-hosted) | Liabilities: balance, rate and type, maturity, next payment, origination | Sandbox adapter |
| Flinks | Flinks Connect iframe (provider-hosted) | Account detail: mortgage balance only | Sandbox adapter |

Anything else (credential scraping, unaccredited aggregators) is not supported.
Accredited Consumer-Driven Banking access (Bank of Canada registry) is expected
2027 or later and would slot in as another adapter.

## Design

`backend/renewal/banklink/`

- `models.py`: `Consent` (provider, scopes, purpose, 1 to 90 days), `LinkSession`,
  `MortgageSnapshot` (only the fields renewal analysis needs, plus `missing`),
  and `reject_credentials`.
- `adapters.py`: `PlaidAdapter` and `FlinksAdapter` map each provider's
  documented response shape to `MortgageSnapshot`. Transports are injected;
  only `SandboxTransport` exists. A non-sandbox transport raises
  `ProductionNotConfigured`, because production access needs a signed provider
  agreement, a security review and a privacy impact assessment first.
- `service.py`: consent-gated flow. A purpose must be `renewal_analysis` or
  `penalty_estimate`, and `mortgage:read` is required. Link ids are returned
  once and stored as SHA-256 digests, provider account ids are hashed before
  storage, and snapshots are cached for at most 30 days. Revoking a consent
  calls the provider's revoke endpoint and deletes snapshots. Lapsed consents
  are purged the same way. Every step is written to an audit trail that never
  includes access handles.
- `to_renewal_inputs` turns a snapshot into pre-filled form values with
  `confirm_required: true` and a list of fields to ask the user for.

## API (sandbox only, `RR_ENABLE_BANKLINK_SANDBOX=1`)

| Endpoint | Purpose |
|---|---|
| `GET /api/v5/banklink/providers` | Providers, mode, `credential_collection: false` |
| `POST /api/v5/banklink/consents` | Record consent (subject, provider, purpose, days) |
| `POST /api/v5/banklink/consents/{id}/session` | Provider widget token or URL |
| `POST /api/v5/banklink/consents/{id}/complete` | Exchange the widget's public token for a link id |
| `GET /api/v5/banklink/links/{link_id}/mortgages` | Mortgage snapshots and pre-fill values |
| `DELETE /api/v5/banklink/consents/{id}` | Revoke: provider access removed, data deleted |

## Before production

1. Signed Plaid or Flinks agreement and production keys kept in a secrets manager.
2. A production transport with request signing, retries and circuit breakers.
3. Persistent, encrypted consent and audit storage tied to authenticated users.
4. Privacy impact assessment (PIPEDA, Quebec Law 25) and consent text review.
5. Check that the provider actually returns mortgage liabilities for each big-six bank.
