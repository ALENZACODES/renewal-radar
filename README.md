# Renewal Radar - Local Mortgage Intelligence

*By John Khan · Alenza Fintech*

## V17 Local Release

On Windows, open **Start Renewal Radar.cmd** in the extracted folder. The portable ZIP requires Python 3.11+ and the existing requirements on a new
computer; the launcher can install them into a local virtual environment while
online. It contains no credentials or bank accounts. This revised build bundles
Windows x64 Tesseract 5.5.3 and English/French high-accuracy models, with licenses.
The installed engine reads scans locally without an OCR account or Internet call.

V17 adds a free on-device mortgage helper, evidence review notes, automatic
dated official rate tracking, locally bundled fonts, interactive charts and
`robots.txt`. The helper uses a small local intent classifier with evidence-based
answers, not a generative large language model. It needs no API key or paid service.
First open the app while the local server is running to cache its offline shell.
Fresh rates need Internet access. PDF/scan extraction and backend calculations
need the local server, but not a remote OCR service. The browser-only offline
helper remains available even if the local server stops.

The final Penn-inspired naval identity uses Inter headings, Noto Sans body text,
Georgia brand lettering, navy/crimson accents and restrained original waves.
The Canada-inspired base styles and Lato fonts remain available underneath.
An original radar/savings R monogram replaces the earlier draft ship emblems.
Inter's tabular numerals improve financial comparisons. Apache ECharts 6.1.0 adds
balance/interest trajectories, reconciled cost breakdowns and a dated public-rate
landscape. These licensed GitHub assets are included locally, with no CDN runtime
requirement. See `docs/OFFLINE_HELPER_V17.md`, `docs/CHARTS_AND_SOURCES_V17.md` and
`docs/VERIFICATION_V17.md` for implementation, provenance and verification limits.

**One-line pitch:** Upload a renewal letter and turn it into an evidence-linked financial comparison, a conditional 2026 Canadian lender-switch assessment, a negotiation script, and an actionable PDF strategy.

**Repository status:** Working, tested **hackathon/MVP application**. It runs locally or via Docker. It is **not deployed**, and no contest submission, registration, bank integration contract, or third-party API purchase has been made. The attached `docs/PRODUCT_MASTER_BLUEPRINT.md` describes the larger intended enterprise platform; code in this repository implements the working modules listed below, not every proposed enterprise feature.

## 1. Run it

Requirements: Python 3.11+, pip; Node 20+ if running the frontend test suite. No npm install or account is required for the demonstration.

```bash
unzip renewal-radar-enterprise-v17-code.zip -d renewal-radar-v17
cd renewal-radar-v17
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
npm test
```

Current verification details are in `docs/VERIFICATION_V16.md`. The suites cover mortgage calculations, document extraction, contract evidence, APIs, reports, review sessions, optional adapter payloads, banking consent scaffolding, and frontend rendering. A live bank connection and optional heavyweight OCR model execution require their separate provider setup.

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

The supplied project briefs name **Build North** and **Nebius × NVIDIA Global AI Hackathon** (deadline October 30, 2026). This package is a separate runnable artifact and does not authorize registration, public GitHub upload, Devpost submission, key creation or paid services. Consult `docs/HACKATHON_DEMO.md` and disclose any previously built scaffolding as required by each contest.

**License:** MIT. No bank or Canadian agency endorses this product. `Maple Bank` is fictional. Rates in the sample are not live bank quotes.

### Auditable amortization exports

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

## V4 implementation increment

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

## V5: controlled official rate collection

V5 adds `backend/renewal/intelligence/collector.py` and
`scripts/collect_official_rates.py`. The scheduled script only visits the
hard-coded official lender URLs in `services/market.py`. It **does not** follow
redirects, infer rates from promotional text, or claim historical coverage for
periods before the collector first ran. A unique, clearly labelled fixed
five-year **posted** table row is required for automatic acceptance; other
pages are quarantined. Attempts, even failures, are written to a separate
SQLite collection journal; verified observations are preserved in the existing
append-only rate archive. No public route triggers collection.

Run one collection cycle (network access is required):

```bash
PYTHONPATH=backend python scripts/collect_official_rates.py
```

View the latest statuses at `/api/v5/rates/collection/status`. For a production
scheduler, run the script through a container cron/CronJob with a persistent
`data/` volume and operational alerting on repeated failures. Respect lender
website terms, robots instructions, and access restrictions; use authorized
feeds whenever available. All results are **public posted-rate observations**,
not individualized offers, lender-approved payout estimates, or historical
rates recovered from an archive.

## V6 incremental implementation (tested)

Added `backend/renewal/broker/renewal_queue.py`: an idempotent,
workspace-scoped renewal milestone queue with 180/120/90/60/30/14/7/0-day
windows, auditable task state transitions and explicit per-client consent
checks at request time. It does not send messages or assume consent.

Four `/api/v6/broker/workspaces/{wid}/renewal-tasks` endpoints support
synchronization, listing, updating and viewing audit events. Broker tokens
from the V4 workspace module are required on every endpoint.

The suite runs with `PYTHONPATH=backend pytest -q tests`, and frontend
checks with `node --test tests/frontend.test.mjs`. V6 adds
`test_renewal_queue_v6.py` and `test_renewal_api_v6.py`.

This is a development checkpoint, not the planned enterprise platform or
an 8-percentage-point source-line increment. A managed production identity
provider, secure encrypted storage, operational monitoring, and privacy review
are prerequisites before using real customer information.

## V7 — Evidence-based penalty payout verification

`renewal.penalty.verification` introduces a versionable reconciliation workflow
for **redacted** lender penalty reference cases. It supports historical payout
statement references and lender calculator results, decimal arithmetic, sample
eligibility controls, configurable money tolerances, detailed variance reports,
and explicit insufficient-evidence outcomes. Synthetic cases never count toward
lender validation claims. A reference match is not lender certification.

Run a local batch with `PYTHONPATH=backend python scripts/verify_penalties.py
reference-cases.json verification-report.json`. The same structural validation
is accessible as `POST /api/penalty/v7/verify` with an object containing a
`cases` array. Do not submit borrowers' raw payout documents or personal data.

The penalty engine is still an estimate: accurate lender contracts, comparison
rate evidence, and dated written payout amounts are needed to qualify each
lender/version for any externally reported accuracy metric.


## V8 Camera OCR

New `/api/v8/camera/inspect`, `/api/v8/camera/ocr`, and `/api/v8/camera/pdf` endpoints normalize document photographs, detect basic capture problems and optionally run local Tesseract OCR. Optional Docling is supported through a separately installed backend; heavy weights are intentionally not bundled. All extracted fields require borrower verification. Supported formats: JPG, PNG, WebP, TIFF. Scan images are not persisted by these endpoints. Install Tesseract on the server for local text extraction. The source code is independently written against public package interfaces; no repository code was copied.

## V9 Consent-Based Banking Foundation

V9 adds `backend/renewal/banking/open_banking.py`, a local sandbox foundation for future consent-based banking connectivity. It does not connect to a real bank, does not return raw tokens, and does not store full account numbers. It implements provider metadata, signed authorization state, session exchange, hashed token-vault records, revocation, account and transaction snapshot import, redaction, mortgage-payment evidence, cashflow summaries and a banking audit log.

New endpoints are under `/api/v9/banking` and `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking`. They require the existing broker token plus current `bank_data_read` consent recorded through the V4 broker consent API. Snapshot import re-checks consent at request time, so revoked consent blocks future import and evidence reads. The evidence output is limited to corroborating payment cadence from imported transactions; it is not a payout statement, affordability approval, underwriting decision or live open-banking feed.

Tests: `tests/test_open_banking_v9.py` covers the service boundary, redaction, state integrity, tenant isolation, consent revocation, import idempotency, evidence and cashflow. `tests/test_open_banking_api_v9.py` covers the HTTP workflow. Production use still requires a regulated provider contract, identity provider, encrypted secret vault, retention policy, privacy impact assessment, consent UX review and operational monitoring.

## V10 OCR Field Review Workflow

V10 adds `backend/renewal/ocr/fields.py`, a deterministic OCR field-review layer for mortgage renewal documents. It accepts OCR text pages from the V8 camera/OCR pipeline or another local OCR engine, validates page limits, computes page source hashes, extracts bounded field candidates, redacts common identifiers in snippets, and produces a borrower-review packet instead of treating OCR as authoritative.

The new `/api/v10/ocr/fields` endpoint returns source-linked candidates, missing required fields, conflicts, confidence labels and a safe mortgage-prefill draft. The new `/api/v10/ocr/review` endpoint applies explicit manual corrections and summarizes whether the reviewed fields are complete enough to prefill a mortgage comparison form. These endpoints do not store raw page text, image bytes, account identifiers or uploaded files.

Supported extraction targets include balance, offered/current rate, payment amount, term, amortization, maturity date, payment frequency, lender name and a masked mortgage reference. Ambiguous dates, low OCR confidence, duplicate values, conflicting candidates and manual corrections are surfaced in the response. Production use still needs human verification, lender-document calibration, retention rules, accessibility review and privacy/security assessment before handling real borrower records.

Tests: `tests/test_ocr_fields_v10.py` covers field normalization, OCR-noise repair, redaction, conflicts, corrections, review summaries, page validation and prefill safety. `tests/test_ocr_fields_api_v10.py` covers the HTTP endpoints and rejection paths.

## V11 Document Understanding, Review Sessions and Modern OCR Adapters

V11 adds a deeper document-understanding layer for mortgage OCR. `backend/renewal/ocr/document_understanding.py` classifies mortgage documents, detects sections and clauses, extracts fine details, identifies interest-rate-differential language, reads contract rate, posted rate, contract discount, mortgage start date, maturity date, term and amortization context, and produces consistency checks plus review questions.

`backend/renewal/ocr/mortgage_terms.py` explains Canadian mortgage terms and calculations, including fixed-rate semi-annual compounding, scheduled payment estimates, contract discount math (`posted rate - contract rate`) and term timeline checks. The companion paper `docs/MORTGAGE_MATH_CODE_WALKTHROUGH_V11.md` explains the formulas and walks through the calculation helper code line by line.

`backend/renewal/ocr/review_sessions.py` adds privacy-safe OCR review sessions backed by SQLite. Sessions store sanitized extraction output, redacted evidence snippets, page hashes, reviewer corrections, approval/rejection decisions, quality gates, audit events and export packets. Raw OCR text and uploaded image bytes are not persisted by the review-session store.

The OCR engine boundary now supports optional adapters for `auto`, `tesseract`, `docling`, `paddleocr`, `easyocr` and `rapidocr`. The source ZIP does not bundle heavy model weights or optional runtimes. If those packages are installed and pinned in a deployment, the adapters can use them; otherwise the `auto` router skips unavailable engines and returns controlled warnings instead of crashing. The registry endpoint explains current integration posture using public project references for Tesseract, Docling, PaddleOCR, EasyOCR and RapidOCR.

New endpoints:

| Endpoint | Action |
| --- | --- |
| `GET /api/v11/ocr/engines` | Lists OCR engine profiles and integration notes |
| `POST /api/v11/ocr/engine-plan` | Recommends an OCR engine path for a document workflow |
| `GET /api/v11/mortgage/terms` | Explains Canadian mortgage terms and formulas |
| `POST /api/v11/ocr/understand` | Runs OCR field extraction plus document understanding |
| `POST /api/v11/ocr/review-sessions` | Creates a token-protected OCR review session |
| `GET /api/v11/ocr/review-sessions/{id}` | Reads a sanitized review session |
| `POST /api/v11/ocr/review-sessions/{id}/corrections` | Applies reviewer corrections |
| `POST /api/v11/ocr/review-sessions/{id}/decisions` | Records field approvals, follow-ups or rejections |
| `POST /api/v11/ocr/review-sessions/{id}/finalize` | Finalizes a review once blocking gates pass |
| `GET /api/v11/ocr/review-sessions/{id}/audit` | Returns session audit events and digest |
| `GET /api/v11/ocr/review-sessions/{id}/export` | Returns a privacy-safe export packet |

Tests: `tests/test_ocr_understanding_v11.py`, `tests/test_ocr_review_sessions_v11.py`, `tests/test_ocr_api_v11.py` and `tests/test_ocr_engines_v11.py`.

## V12 Contract Intelligence

V12 adds `backend/renewal/ocr/contract_intelligence.py`, a deterministic contract-intelligence layer over the V11 mortgage-document understanding packet. It builds an evidence graph from fields, clauses, checks, sections, fine details and Canadian mortgage calculations; scores practical review risks; generates lender questions; and answers reviewer questions from evidence IDs instead of making free-form legal claims.

V12 also adds `backend/renewal/ocr/contract_playbook.py`. The playbook converts the brief into review tasks: critical missing-field tasks, lender question tasks, verification tasks, comparison-prefill gates, manual approval gates, a field-review matrix and a maturity-aware timeline. This is the operational layer that helps a reviewer act on the contract intelligence without pretending the OCR result is automatically final.

`backend/renewal/ocr/contract_sources.py` records the public source map used as design input: Docling, Unstructured, Presidio, CUAD, LEGAL-BERT/Contracts-BERT and LayoutParser. These are not bundled dependencies and no repository code is copied. They shape the architecture: structure-aware parsing, element partitioning, privacy boundaries, clause-grounded contract review and future optional classifier/layout adapters.

The concept note `docs/CONTRACT_INTELLIGENCE_CONCEPT_V12.md` explains the design in plain text. The key idea is that a mortgage contract should be represented as related evidence, not flat OCR text: posted rate, contract rate, contract discount, mortgage start date, maturity date, term, amortization, payment, IRD clauses and lender questions are connected through a graph.

New endpoints:

| Endpoint | Action |
| --- | --- |
| `GET /api/v12/contract-intelligence/sources` | Lists public source-map references and design principles |
| `POST /api/v12/contract-intelligence/brief` | Returns evidence graph, risks, readiness, lender questions and optional answer |
| `POST /api/v12/contract-intelligence/answer` | Returns a compact evidence-grounded answer package |
| `POST /api/v12/contract-intelligence/playbook` | Returns prioritized review tasks, prefill gates, field-review matrix and timeline |

Tests: `tests/test_contract_intelligence_v12.py`, `tests/test_contract_playbook_v12.py` and `tests/test_contract_intelligence_api_v12.py`.

## V13 No-Dependency Contract Research Radar

V13 adds `backend/renewal/ocr/contract_math_v13.py`, a self-contained Canadian mortgage math and disclosure audit. It explains contract discount math, three-month-interest estimates, posted-rate-minus-discount IRD scenarios, term timeline checks, renewal timing and lender disclosure prompts. These are local review estimates only; lender payout statements and contract wording control final amounts.

V13 also adds `backend/renewal/ocr/research_radar_v13.py`. This is the "double search" layer: it records current web/GitHub research references such as Docling, Unstructured, PaddleOCR, olmOCR, Marker, Surya and FCAC mortgage guidance, then converts those ideas into in-house adapter tasks. The public projects are references, not runtime requirements. V13 does not import those repositories, download models, copy GitHub code or add new package dependencies.

`backend/renewal/ocr/contract_packet_v13.py` turns the brief, playbook, math audit and research radar into a safe lender/reviewer packet. It includes a borrower-safe snapshot, lender questions, disclosure prompts, an evidence appendix and signoff gates. It excludes raw OCR text and mortgage/account identifiers from the packet output.

The concept note `docs/CONTRACT_RESEARCH_RADAR_V13.md` explains the design in plain text. The core idea is to use the outside ecosystem as a map while keeping Renewal Radar's actual contract intelligence local, deterministic and testable.

New endpoints:

| Endpoint | Action |
| --- | --- |
| `GET /api/v13/contract-intelligence/research-sources` | Lists web/GitHub research references and the no-dependency policy |
| `POST /api/v13/contract-intelligence/math-audit` | Returns formula walkthroughs, penalty scenarios, disclosure prompts and renewal timing |
| `POST /api/v13/contract-intelligence/research-radar` | Returns adapter needs, source scores, in-house adapter tasks, math audit and playbook summary |
| `POST /api/v13/contract-intelligence/lender-packet` | Returns a borrower-safe lender/reviewer packet with questions, evidence appendix and signoff gates |

Tests: `tests/test_contract_math_v13.py`, `tests/test_research_radar_v13.py`, `tests/test_contract_packet_v13.py` and `tests/test_contract_research_api_v13.py`.

## V14 Optional Dependency Adapter Planning

V14 adds `backend/renewal/ocr/dependency_adapters_v14.py`, a dependency-aware adapter planner for current OCR/document-intelligence projects. It builds in optional profiles for Docling, Unstructured, PaddleOCR, Surya, Marker and olmOCR, detects whether those packages are installed, ranks which adapter shape best fits the mortgage document, and returns exact input contracts for future integration.

The optional dependency list is captured in `requirements-ocr-optional.txt`. These packages are not added to the base `requirements.txt`, because they can be large, model-dependent or license-sensitive. The default app remains runnable with the base dependencies; optional engines are detected and planned, not forced.

The concept note `docs/OPTIONAL_OCR_DEPENDENCIES_V14.md` explains the dependency policy and adapter input contracts.

New endpoints:

| Endpoint | Action |
| --- | --- |
| `GET /api/v14/ocr/optional-dependencies` | Lists optional OCR/document dependencies, GitHub references and requirement lines |
| `POST /api/v14/contract-intelligence/dependency-plan` | Returns detected dependency status, ranked adapter profiles, input contracts and local fallback chain |
| `POST /api/v14/contract-intelligence/adapter-readiness` | Returns operator gates, execution steps and blockers for optional adapter use |

Tests: `tests/test_dependency_adapters_v14.py` and `tests/test_dependency_adapters_api_v14.py`.

## V15 Adapter Output Normalization

V15 adds `backend/renewal/ocr/adapter_output_normalizer_v15.py`, a local normalizer for outputs shaped like Docling, Unstructured, PaddleOCR, Surya, Marker and olmOCR. It accepts plain dictionaries/lists, redacts text, extracts spans/tables, builds OCR pages, and flags quality signals such as money, rates, dates, penalty language and low-confidence lines.

V15 also adds `backend/renewal/ocr/adapter_quality_harness_v15.py`. The harness runs normalized adapter output through the V12-V14 contract stack and produces a scorecard, quality gates and next actions. This lets Renewal Radar use best current GitHub-style OCR inputs without making those external engines mandatory.

`backend/renewal/ocr/adapter_workbench_v15.py` compares multiple adapter payloads side by side, scores them, selects the strongest OCR input and reports consensus strength. This is useful when the same mortgage PDF is processed by more than one optional reader.

`backend/renewal/ocr/adapter_reconciliation_v15.py` reconciles field values across adapter candidates. It votes on balance, contract rate, posted rate, contract discount, offered rate, term, amortization, mortgage date, maturity date, payment and frequency, then marks each field as consensus, conflict, single-source or missing.

`backend/renewal/ocr/adapter_benchmark_suite_v15.py` adds a repeatable synthetic benchmark suite for current GitHub-style adapter shapes. It runs complete, noisy, low-confidence, thin and multi-adapter conflict cases through the normalizer, quality harness and reconciliation layer so adapter changes can be checked without installing heavyweight OCR packages.

The concept note `docs/ADAPTER_NORMALIZATION_V15.md` explains how adapter-shaped outputs become Renewal Radar evidence.

New endpoints:

| Endpoint | Action |
| --- | --- |
| `POST /api/v15/ocr/adapter-normalize` | Normalizes adapter-shaped output into OCR pages, spans, tables and quality flags |
| `POST /api/v15/ocr/adapter-preview` | Returns a compact preview and validation summary for adapter output |
| `POST /api/v15/ocr/adapter-evaluate` | Runs normalized adapter output through contract intelligence, math audit and dependency planning |
| `POST /api/v15/ocr/adapter-workbench` | Compares multiple adapter payloads and selects the strongest input for contract review |
| `POST /api/v15/ocr/adapter-reconcile` | Reconciles mortgage fields across adapter candidates and returns reviewer decisions |
| `POST /api/v15/ocr/adapter-benchmark` | Runs synthetic adapter benchmark cases for selected adapter shapes |

Tests: `tests/test_adapter_output_normalizer_v15.py`, `tests/test_adapter_quality_harness_v15.py`, `tests/test_adapter_workbench_v15.py`, `tests/test_adapter_reconciliation_v15.py`, `tests/test_adapter_benchmark_suite_v15.py` and `tests/test_adapter_api_v15.py`.

## V16 Mortgage Document Evidence Audit

V16 adds a scoped evidence ledger and audit for mortgage document details. Original mortgage, renewal offer, payout statement, and unassigned facts remain separate. The audit checks rate discounts in percentage points, original-to-renewal rate changes, term calendars including leap years, term versus amortization, and distinct offer-expiry dates. Conflicting values remain visible until a reviewer supplies a scoped correction.

Interest/intrest and differential/differental variants are recognized. IRD wording is recorded as mentioned, negated, conditional, or illustrative. Missing comparison rates produce review prompts instead of using a renewal offer as a substitute. Ambiguous slash dates, number grouping, and repaired OCR digits are held for review.

Letter X-Ray now shows Contract details automatically after a PDF upload. Each fact and check links to expandable page/line evidence. Searchable PDF text is read in full within the 16-page and 25,000-character-per-page limits; a short preview is not used as the audit source. Image-only PDFs require OCR text or a searchable export.

- `POST /api/v16/ocr/semantic-audit` accepts OCR pages, optional `as_of`, `min_confidence`, and scoped `corrections`.
- `POST /api/v16/ocr/semantic-audit/pdf` accepts a PDF upload and returns the audit.
- Corrections use keys such as `original.contract_rate`, `renewal.term_months`, and `payout.comparison_rate`. Rate corrections are numeric percentages, durations are months, and dates use ISO format.

V16 uses the existing runtime dependencies. It adds no model download, API subscription, or new package requirement. Its deterministic patterns cover the tested labels and conditions; they do not establish comprehensive legal understanding of every possible contract.

See `docs/SEMANTIC_AUDIT_V16.md` for the evidence and calculation design, and `docs/VERIFICATION_V16.md` for release verification. Tests are `tests/test_semantic_evidence_v16.py`, `tests/test_document_semantic_auditor_v16.py`, `tests/test_document_semantic_api_v16.py`, and `tests/semantic-audit.test.mjs`.
