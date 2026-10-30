# Renewal Radar 2.0 — Runnable Canadian Mortgage Renewal Intelligence

**One-line pitch:** Upload a renewal letter and turn it into an evidence-linked financial comparison, a conditional 2026 Canadian lender-switch assessment, a negotiation script, and an actionable PDF strategy.

**Repository status:** Working, tested **hackathon/MVP application**, not a completed 50,000-line, enterprise-certified deployment. It runs locally or via Docker. It is **not deployed**, and no contest submission, registration, bank integration contract, or third-party API purchase has been made. The attached `docs/PRODUCT_MASTER_BLUEPRINT.md` describes the larger intended enterprise platform; code in this repository implements the working modules listed below, not every proposed enterprise feature.

## 1. Run it

Requirements: Python 3.11+, pip; Node 20+ if running the frontend test suite. No npm install or account is required for the demonstration.

```bash
git clone https://github.com/ALENZACODES/renewal-radar.git
cd renewal-radar
python -m venv .venv
source .venv/bin/activate                 # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=backend uvicorn renewal.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The first screen contains a complete fictional sample. Under Letter X-Ray, press **Load sample PDF** to see the extraction flow. The sample fixtures are in `fixtures/`.

**Docker alternative:**

```bash
docker compose up --build
```

Then visit http://localhost:8000. The container uses a persisted SQLite volume for local demonstration.

**Optional AI and web search:**

```bash
cp .env.example .env
# Add NEBIUS_API_KEY, NEBIUS_MODEL and optionally TAVILY_API_KEY.
# Load .env in your shell (or provide env_file to Docker Compose).
```

No external service credentials are bundled. Model availability and account entitlements vary; set `NEBIUS_MODEL` to a **NVIDIA Nemotron model actually supported by your Nebius Token Factory account**. When no key is supplied, the mathematics, rule engine, reports and source links work normally and AI explanations fall back to deterministic language. The optional AI integration has not been exercised against a live Nebius account in this build.

## 2. What you can use now

The nine-screen interface provides:

1. **Overview:** mortgage balance, offered rate, payment, potential alternative savings, balance curves and conditional switching signal.
2. **Letter X-Ray:** upload a text-based PDF; bounded, in-memory PyMuPDF extraction; field evidence with page references; editable validation. Optional Nemotron enhancement suggests *missing* fields only, with literal-source validation.
3. **Offer comparison:** fixed vs variable, 12–60 month analysis horizons, different terms, six payment frequencies, alternative rate/fees/fee credit, annual lump sums and monthly extra payments; equal-horizon interest and ending-principal economics.
4. **Switch eligibility:** insured and uninsured routing; FRFI, stand-alone, combined loan, cash-out, amortization and $3,000 fee predicates; never labels a user “approved.”
5. **Rate intelligence:** current-on-request official Bank of Canada Valet observations (when Internet access is available), publication dates and source URLs, official six-bank pages and optional conservative HTML parsing of unambiguous five-year fixed posted rates. If ambiguous or blocked, a bank rate remains **unverified**, never fabricated.
6. **Penalty workbench:** three-month-interest estimate, illustrative simple or posted-minus-discount IRD, open/maturity and variable pathways; insists on the lender’s written payout statement.
7. **Negotiation coach:** editable scenario-based telephone script, counteroffer email and seven lender questions; distinguish hypothetical numbers from verified offers.
8. **Action plan:** eight maturity-relative milestones, completion tracking in the active tab and downloadable RFC5545 `.ics` calendar.
9. **Strategy report:** downloadable self-contained source-cited PDF including amortization costs, conditional switch rules, lender conversation and calendar steps; saved case with opaque token; 1–168-hour read-only share links and revocation.

A **full eight-step agent run** orchestrates source retrieval, underwriting classification, deterministic comparison, rate-path stress scenarios, negotiation, action planning, and optional NVIDIA Nemotron explanation. Tool execution is the system of record; the model does not calculate mortgage amortization or invent lender quotes.

### Demonstration data (fictional)

- Opening mortgage: **$480,000**, offer **5.49%**, **19-year** remaining amortization, **3-year** renewal term.
- Alternative: **4.49%**, hypothetical — *not* a guaranteed or discovered lender quote.
- Monthly principal-and-interest payments under Canadian nominal semiannual compounding: **$3,378.66** and **$3,122.52**.
- Over 36 months without switching costs: illustrative interest difference **$13,756.07**; ending debt difference **$4,535.04**. Payment difference and interest savings are **not additive**.

See `fixtures/fictional-renewal-letter.pdf` and `fixtures/fictional-renewal-strategy.pdf`.

## 3. Verification

```bash
PYTHONPATH=backend pytest -q
node --test tests/frontend.test.mjs
```

Current suite: **142 Python tests and 6 Node tests passing**, run on every push by GitHub Actions. Tests cover the OSFI branching logic, mathematics, CSV-free official rate parsing, document extraction, HTTP APIs, PDF generation, read-only case sharing, rate ingestion idempotence and all nine view template renderers. Responsive display has not yet been screenshot-verified across devices. Use `docs/BROWSER_ACCEPTANCE.md` to run the manual checks on your machine.

## 4. Application architecture

```
frontend/index.html + frontend/assets/app.css + frontend/js/*
                 │  same-origin HTTPS/JSON (local HTTP demo)
                 ▼
backend/renewal/main.py  ── FastAPI schemas + validation
   ├─ domain/mortgage_math.py     ◀ deterministic Canadian amortization
   ├─ domain/rules.py             ◀ 2026 MQR and switches + IRD proxy
   ├─ services/extract.py        ◀ PDF -> source-linked fields
   ├─ services/agent.py          ◀ optional Nebius Nemotron explanations
   ├─ services/market.py         ◀ official Bank of Canada Valet
   ├─ providers/bank_rates.py    ◀ conservative public lender HTML parser
   ├─ providers/tavily.py        ◀ optional official source discovery
   ├─ services/negotiation.py   ◀ scripts + offer truth labels
   ├─ services/plan.py          ◀ milestone dates + ICS
   ├─ services/report.py        ◀ ReportLab PDF output
   ├─ services/store.py         ◀ SQLAlchemy cases + expiring shares
   └─ pipelines/ingest.py       ◀ idempotent source snapshot CLI
```

The OpenAPI browser UI is available at `/docs`, and the machine-readable schema at `/openapi.json`.

## 5. Key HTTP endpoints

| Endpoint | Action |
| --- | --- |
| `GET /api/health` | Health and connector configuration status (never secret values) |
| `GET /api/health/live` | Liveness probe |
| `GET /api/health/ready` | Readiness: case store, frontend assets, connector flags and circuit-breaker state; 503 when degraded |
| `GET /api/demo` | Synthetic mortgage and illustrative alternatives |
| `GET /api/demo/sample.pdf` | Synthetic renewal letter |
| `POST /api/documents/extract` | Parse bounded PDF upload, page-linked fields |
| `POST /api/analyze` | Deterministic comparison, rules, scenarios and plan |
| `POST /api/agent/run` | Eight-step orchestrated agent output and trace |
| `POST /api/agent/insight` | Optional Nemotron narrative grounded in verified results |
| `GET /api/market` | Bank of Canada official observations |
| `GET /api/market/banks/live` | Six official lender-page checks, fail closed |
| `GET /api/market/discover` | Optional Tavily source discovery; unverified |
| `POST /api/penalty` | Interest/IRD proxy |
| `POST /api/negotiation` | Script and questions |
| `POST /api/report/pdf` | Download report |
| `GET /api/calendar/{YYYY-MM-DD}.ics` | Calendar reminders |
| `POST /api/cases` | Save JSON workspace; returns access token |
| `GET/PUT /api/cases/{id}` | Requires private `X-Case-Token` |
| `POST /api/cases/{id}/share` | Create expiring read-only share |
| `GET /api/shares/{token}` | Read-only share, no PDF bytes |
| `DELETE /api/cases/{id}/shares/{token}` | Revoke a share with case token |

## 6. Data and calculations

The fixed-rate model assumes the standard Canadian nominal APR compounded semiannually. Variable-rate paths use a stated monthly-compounding assumption. Some mortgages have different interest-day conventions and payment structures, so lender payout and schedule comparisons may differ. Scenario costs are evaluated as **all principal-and-interest cash payments + ending debt + net fees − starting debt**, using consistent term horizons. New rates following an expiring 1/2/3-year term are **not forecast**; those results are flagged non-comparable where appropriate. Stress paths are hypothetical rate changes, not future Bank of Canada predictions.

The OSFI minimum qualifying rate for most new uninsured underwriting is **max(contract rate + 2.00 percentage points, 5.25%)**. For eligible existing uninsured stand-alone FRFI-to-FRFI straight switches at renewal, OSFI no longer prescribes that rate (November 21, 2024). Exemptions are conditional and **do not grant automatic approval**. Separate insured and portfolio-insured renewal pathways are annotated; no blanket claim is made about all lenders.

Official sources are catalogued in `docs/CANADIAN_RULES_AND_SOURCES.md`.

## 7. Security, limitations and commercialization

**Do not use this MVP to process actual personal financial data on a public server without a security and compliance review.** Original uploaded PDF bytes are held in request memory, validated, parsed and discarded, but manually saved structured mortgage fields reside in **unencrypted SQLite**. Access-control uses per-case bearer tokens, not account-level identity or broker tenant isolation. A public commercial release requires Clerk/OIDC or equivalent authentication, encryption-at-rest and managed key rotation, tenant authorization, rate limiting, PDF scan sandboxing, backups, privacy counsel review, retention/deletion workflows, audit trails, bank-rate licensing/terms and a lender/insurance rules review. It does **not** provide a guaranteed personalized quote, regulated mortgage advice, borrower approval, a real broker referral, an OCR service for scans, or a mortgage application integration.

See `docs/SECURITY_AND_RELEASE_GATE.md` and `docs/PRODUCT_MASTER_BLUEPRINT.md` for the full-scale backlog.

## 8. Hackathons

The supplied project briefs name **Build North** (October 16–25, 2026) and **Nebius × NVIDIA Global AI Hackathon** (deadline October 30, 2026). This package is a separate runnable artifact and does not authorize registration, public GitHub upload, Devpost submission, key creation or paid services. Consult `docs/HACKATHON_DEMO.md` and disclose any previously built scaffolding as required by each contest.

**License:** MIT. No bank or Canadian agency endorses this product. `Maple Bank` is fictional. Rates in the sample are not live bank quotes.

### Auditable amortization exports (added October 2026)

The strategy report screen includes **Download amortization CSV**. The new
`POST /api/ledger.csv` route accepts the same `AnalyzeRequest` as `/api/analyze`
and returns an Excel-compatible UTF-8 CSV with a payment-by-payment ledger for
all scenarios. `POST /api/ledger/annual` returns payment-year summaries including
annual interest, principal, regular-plus-extra cash paid, and outstanding balance.
Both routes use the deterministic `simulate()` function, not a model-generated
amortization schedule. A lender may use different posting/rounding conventions.
The API never stores the exported ledger; model assumptions should always be
confirmed with a lender.

## Enterprise expansion: penalty engine v3

This branch adds versioned lender-method profiles, an independent `Decimal` penalty engine, auditable outputs, two v3 endpoints, and dedicated unit/API tests. See [penalty v3 documentation](docs/PENALTY_ENGINE_V3.md) and [50k+ line production file manifest](docs/ENTERPRISE_50000_LINE_FILE_MANIFEST.md). The 77,400-line manifest is a **target**, not a claim about implemented code. Existing v2 endpoints remain for compatibility.

## V4 implementation increment (October 2026)

The codebase now includes `backend/renewal/intelligence/rate_history.py`, an
append-only historical rate observation store. Every rate observation carries a
product and lender, publication date, collection date, source URL, document hash,
and excerpt. The `historical-discount` API returns an evidence-backed *estimate*
only when a near-origination posted rate exists; no historical prices are invented.
Rate submissions require a configured `RR_RATE_INGEST_KEY` of 24+ characters.
Actual automated scraping jobs and verified lender extraction selectors are a
separate uncompleted integration.

`backend/renewal/broker/workspace.py` provides opaque-token tenant-separated
broker workspaces, client aliases, consent-grant and revocation events, and an
audit trail. To allow **development-only** workspace creation, set
`RR_ENABLE_DEMO_WORKSPACES=1`; it is off by default. Do **not** expose this
demo identity scheme to real consumer information on the public internet.
A production identity provider, authorization audit, encryption and privacy
impact assessment are still needed. The consent tracker does not implement a
bank data connector or establish authorization with any financial institution.

The V4 APIs are under `/api/v4/rates` and `/api/v4/broker`. Their HTTP and unit
contracts are exercised by `tests/test_v4_api.py` and `tests/test_v4_services.py`.
Count production progress by genuine handwritten source code, not proposed
manifest estimates, vendored code, generated fixtures or database rows.

## Platform hardening (CI, rate limiting, resilience)

- **CI:** `.github/workflows/ci.yml` runs the Python suite on 3.11, 3.12 and 3.13,
  the frontend syntax check and Node tests, and a Docker build on every push and
  pull request. `.github/workflows/security.yml` runs `pip-audit`, Bandit and a
  gitleaks secret scan, plus a weekly scheduled run.
- **Rate limiting:** `backend/renewal/security/rate_limit.py` is a sliding-window
  limiter applied to `/api/*`, with tighter budgets for PDF extraction, agent,
  report and market routes. Blocked requests get `429` with `Retry-After`. It is
  in-process, so a multi-instance deployment needs a shared store. Disable with
  `RR_RATE_LIMIT=0`.
- **Circuit breakers:** `backend/renewal/resilience/circuit_breakers.py` gives
  optional connectors closed, open and half-open states with a single trial call,
  so a failing third-party source can't stall the deterministic engine.
- **Health probes:** `backend/renewal/observability/health.py` backs
  `/api/health/live` and `/api/health/ready`. Probe output never includes secret
  values or raw exception messages.
