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
