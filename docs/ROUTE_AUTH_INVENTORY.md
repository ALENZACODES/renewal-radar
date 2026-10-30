# Route auth inventory (security-data-gates)

App-level `Depends(require_api_access)` applies to all routes. Classification below is about **additional** resource credentials.

| Was open? | Methods | Path | Resource auth | File:line |
|---|---|---|---|---|
| no | GET | `/` | PUBLIC allowlist | `backend/renewal/main.py:312` |
| **YES — was open** | POST | `/api/agent/insight` | none (API key gate only) | `backend/renewal/main.py:168` |
| **YES — was open** | POST | `/api/agent/run` | none (API key gate only) | `backend/renewal/main.py:177` |
| **YES — was open** | GET | `/api/agent/tools` | none (API key gate only) | `backend/renewal/main.py:213` |
| **YES — was open** | POST | `/api/analyze` | none (API key gate only) | `backend/renewal/main.py:157` |
| **YES — was open** | GET | `/api/calendar/{maturity_date}.ics` | none (API key gate only) | `backend/renewal/main.py:257` |
| **YES — was open** | POST | `/api/cases` | none (API key gate only) | `backend/renewal/main.py:263` |
| had resource token | GET | `/api/cases/{uid}` | x-case-token | `backend/renewal/main.py:272` |
| had resource token | PUT | `/api/cases/{uid}` | x-case-token | `backend/renewal/main.py:276` |
| had resource token | POST | `/api/cases/{uid}/share` | x-case-token | `backend/renewal/main.py:283` |
| had resource token | DELETE | `/api/cases/{uid}/shares/{share_token}` | x-case-token | `backend/renewal/main.py:296` |
| **YES — was open** | GET | `/api/demo` | none (API key gate only) | `backend/renewal/main.py:108` |
| **YES — was open** | GET | `/api/demo/sample-scan.png` | none (API key gate only) | `backend/renewal/main.py:121` |
| **YES — was open** | GET | `/api/demo/sample.pdf` | none (API key gate only) | `backend/renewal/main.py:116` |
| **YES — was open** | POST | `/api/documents/extract` | none (API key gate only) | `backend/renewal/main.py:125` |
| **YES — was open** | GET | `/api/health` | none (API key gate only) | `backend/renewal/main.py:102` |
| no | GET | `/api/health/live` | PUBLIC allowlist | `backend/renewal/routers/v5.py:83` |
| no | GET | `/api/health/ready` | PUBLIC allowlist | `backend/renewal/routers/v5.py:87` |
| **YES — was open** | POST | `/api/ledger.csv` | none (API key gate only) | `backend/renewal/main.py:238` |
| **YES — was open** | POST | `/api/ledger/annual` | none (API key gate only) | `backend/renewal/main.py:244` |
| **YES — was open** | GET | `/api/market` | none (API key gate only) | `backend/renewal/main.py:223` |
| **YES — was open** | GET | `/api/market/banks/live` | none (API key gate only) | `backend/renewal/main.py:226` |
| **YES — was open** | GET | `/api/market/discover` | none (API key gate only) | `backend/renewal/main.py:231` |
| **YES — was open** | GET | `/api/market/lenders` | none (API key gate only) | `backend/renewal/main.py:235` |
| **YES — was open** | POST | `/api/negotiation` | none (API key gate only) | `backend/renewal/main.py:220` |
| **YES — was open** | POST | `/api/penalty` | none (API key gate only) | `backend/renewal/main.py:217` |
| **YES — was open** | POST | `/api/penalty/v3/estimate` | none (API key gate only) | `backend/renewal/main.py:357` |
| **YES — was open** | GET | `/api/penalty/v3/lenders` | none (API key gate only) | `backend/renewal/main.py:347` |
| **YES — was open** | GET | `/api/penalty/v3/methods` | none (API key gate only) | `backend/renewal/routers/v5.py:301` |
| **YES — was open** | POST | `/api/penalty/v3/workbench` | none (API key gate only) | `backend/renewal/routers/v5.py:276` |
| **YES — was open** | POST | `/api/penalty/v7/verify` | none (API key gate only) | `backend/renewal/main.py:633` |
| **YES — was open** | GET | `/api/policy` | none (API key gate only) | `backend/renewal/main.py:301` |
| **YES — was open** | GET | `/api/ratewatch/backtest` | none (API key gate only) | `backend/renewal/ratewatch/api.py:157` |
| **YES — was open** | POST | `/api/ratewatch/extras/{tool}` | none (API key gate only) | `backend/renewal/ratewatch/api.py:201` |
| **YES — was open** | POST | `/api/ratewatch/forecast` | none (API key gate only) | `backend/renewal/ratewatch/api.py:150` |
| **YES — was open** | POST | `/api/ratewatch/letter` | none (API key gate only) | `backend/renewal/ratewatch/api.py:170` |
| **YES — was open** | GET | `/api/ratewatch/live` | none (API key gate only) | `backend/renewal/ratewatch/api.py:232` |
| **YES — was open** | POST | `/api/ratewatch/live/refresh` | none (API key gate only) | `backend/renewal/ratewatch/api.py:238` |
| **YES — was open** | POST | `/api/ratewatch/penalty` | none (API key gate only) | `backend/renewal/ratewatch/api.py:144` |
| **YES — was open** | GET | `/api/ratewatch/rates/{lender}` | none (API key gate only) | `backend/renewal/ratewatch/api.py:133` |
| **YES — was open** | POST | `/api/report/pdf` | none (API key gate only) | `backend/renewal/main.py:248` |
| capability | GET | `/api/shares/{share_token}` | path token | `backend/renewal/main.py:290` |
| **YES — was open** | POST | `/api/v10/ocr/fields` | none (API key gate only) | `backend/renewal/main.py:937` |
| **YES — was open** | POST | `/api/v10/ocr/review` | none (API key gate only) | `backend/renewal/main.py:945` |
| **YES — was open** | GET | `/api/v11/mortgage/terms` | none (API key gate only) | `backend/renewal/main.py:966` |
| **YES — was open** | POST | `/api/v11/ocr/engine-plan` | none (API key gate only) | `backend/renewal/main.py:959` |
| **YES — was open** | GET | `/api/v11/ocr/engines` | none (API key gate only) | `backend/renewal/main.py:955` |
| **YES — was open** | POST | `/api/v11/ocr/review-sessions` | none (API key gate only) | `backend/renewal/main.py:1171` |
| had resource token | GET | `/api/v11/ocr/review-sessions/{session_id}` | x-ocr-review-token | `backend/renewal/main.py:1187` |
| had resource token | GET | `/api/v11/ocr/review-sessions/{session_id}/audit` | x-ocr-review-token | `backend/renewal/main.py:1227` |
| had resource token | POST | `/api/v11/ocr/review-sessions/{session_id}/corrections` | x-ocr-review-token | `backend/renewal/main.py:1196` |
| had resource token | POST | `/api/v11/ocr/review-sessions/{session_id}/decisions` | x-ocr-review-token | `backend/renewal/main.py:1206` |
| had resource token | GET | `/api/v11/ocr/review-sessions/{session_id}/export` | x-ocr-review-token | `backend/renewal/main.py:1236` |
| had resource token | POST | `/api/v11/ocr/review-sessions/{session_id}/finalize` | x-ocr-review-token | `backend/renewal/main.py:1217` |
| **YES — was open** | POST | `/api/v11/ocr/understand` | none (API key gate only) | `backend/renewal/main.py:970` |
| **YES — was open** | POST | `/api/v12/contract-intelligence/answer` | none (API key gate only) | `backend/renewal/main.py:992` |
| **YES — was open** | POST | `/api/v12/contract-intelligence/brief` | none (API key gate only) | `backend/renewal/main.py:983` |
| **YES — was open** | POST | `/api/v12/contract-intelligence/playbook` | none (API key gate only) | `backend/renewal/main.py:1006` |
| **YES — was open** | GET | `/api/v12/contract-intelligence/sources` | none (API key gate only) | `backend/renewal/main.py:979` |
| **YES — was open** | POST | `/api/v13/contract-intelligence/lender-packet` | none (API key gate only) | `backend/renewal/main.py:1038` |
| **YES — was open** | POST | `/api/v13/contract-intelligence/math-audit` | none (API key gate only) | `backend/renewal/main.py:1019` |
| **YES — was open** | POST | `/api/v13/contract-intelligence/research-radar` | none (API key gate only) | `backend/renewal/main.py:1028` |
| **YES — was open** | GET | `/api/v13/contract-intelligence/research-sources` | none (API key gate only) | `backend/renewal/main.py:1015` |
| **YES — was open** | POST | `/api/v14/contract-intelligence/adapter-readiness` | none (API key gate only) | `backend/renewal/main.py:1070` |
| **YES — was open** | POST | `/api/v14/contract-intelligence/dependency-plan` | none (API key gate only) | `backend/renewal/main.py:1059` |
| **YES — was open** | GET | `/api/v14/ocr/optional-dependencies` | none (API key gate only) | `backend/renewal/main.py:1048` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-benchmark` | none (API key gate only) | `backend/renewal/main.py:1132` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-evaluate` | none (API key gate only) | `backend/renewal/main.py:1095` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-normalize` | none (API key gate only) | `backend/renewal/main.py:1081` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-preview` | none (API key gate only) | `backend/renewal/main.py:1088` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-reconcile` | none (API key gate only) | `backend/renewal/main.py:1118` |
| **YES — was open** | POST | `/api/v15/ocr/adapter-workbench` | none (API key gate only) | `backend/renewal/main.py:1105` |
| **YES — was open** | POST | `/api/v16/ocr/semantic-audit` | none (API key gate only) | `backend/renewal/main.py:1146` |
| **YES — was open** | POST | `/api/v16/ocr/semantic-audit/pdf` | none (API key gate only) | `backend/renewal/main.py:1157` |
| **YES — was open** | POST | `/api/v17/documents/read` | none (API key gate only) | `backend/renewal/main.py:140` |
| **YES — was open** | POST | `/api/v17/market/refresh` | none (API key gate only) | `backend/renewal/main.py:329` |
| **YES — was open** | GET | `/api/v17/market/snapshot` | none (API key gate only) | `backend/renewal/main.py:324` |
| **YES — was open** | POST | `/api/v17/penalty/timeline` | none (API key gate only) | `backend/renewal/main.py:353` |
| **YES — was open** | POST | `/api/v4/broker/workspaces` | none (API key gate only) | `backend/renewal/main.py:504` |
| had resource token | GET | `/api/v4/broker/workspaces/{wid}/audit` | x-broker-token | `backend/renewal/main.py:550` |
| had resource token | GET | `/api/v4/broker/workspaces/{wid}/clients` | x-broker-token | `backend/renewal/main.py:527` |
| had resource token | POST | `/api/v4/broker/workspaces/{wid}/clients` | x-broker-token | `backend/renewal/main.py:517` |
| had resource token | POST | `/api/v4/broker/workspaces/{wid}/clients/{cid}/consents` | x-broker-token | `backend/renewal/main.py:532` |
| had resource token | GET | `/api/v4/broker/workspaces/{wid}/clients/{cid}/consents/{scope}` | x-broker-token | `backend/renewal/main.py:544` |
| **YES — was open** | GET | `/api/v4/rates/historical-discount` | none (API key gate only) | `backend/renewal/main.py:495` |
| **YES — was open** | GET | `/api/v4/rates/history` | none (API key gate only) | `backend/renewal/main.py:483` |
| had resource token | POST | `/api/v4/rates/observations` | x-rate-ingest-key | `backend/renewal/main.py:471` |
| **YES — was open** | POST | `/api/v5/banklink/consents` | none (API key gate only) | `backend/renewal/routers/v5.py:106` |
| **YES — was open** | DELETE | `/api/v5/banklink/consents/{cid}` | none (API key gate only) | `backend/renewal/routers/v5.py:165` |
| **YES — was open** | POST | `/api/v5/banklink/consents/{cid}/complete` | none (API key gate only) | `backend/renewal/routers/v5.py:142` |
| **YES — was open** | POST | `/api/v5/banklink/consents/{cid}/session` | none (API key gate only) | `backend/renewal/routers/v5.py:127` |
| **YES — was open** | GET | `/api/v5/banklink/links/{link_id}/mortgages` | none (API key gate only) | `backend/renewal/routers/v5.py:153` |
| **YES — was open** | GET | `/api/v5/banklink/providers` | none (API key gate only) | `backend/renewal/routers/v5.py:98` |
| had resource token | GET | `/api/v5/broker/workspaces/{wid}/clients/{cid}` | x-broker-token | `backend/renewal/routers/v5.py:186` |
| had resource token | PATCH | `/api/v5/broker/workspaces/{wid}/clients/{cid}/profile` | x-broker-token | `backend/renewal/routers/v5.py:198` |
| had resource token | POST | `/api/v5/broker/workspaces/{wid}/clients/{cid}/stage` | x-broker-token | `backend/renewal/routers/v5.py:218` |
| had resource token | POST | `/api/v5/broker/workspaces/{wid}/clients/{cid}/tasks` | x-broker-token | `backend/renewal/routers/v5.py:233` |
| had resource token | GET | `/api/v5/broker/workspaces/{wid}/dashboard` | x-broker-token | `backend/renewal/routers/v5.py:174` |
| had resource token | GET | `/api/v5/broker/workspaces/{wid}/leads` | x-broker-token | `backend/renewal/routers/v5.py:432` |
| had resource token | POST | `/api/v5/broker/workspaces/{wid}/leads/{lead_id}/reveal` | x-broker-token | `backend/renewal/routers/v5.py:437` |
| had resource token | POST | `/api/v5/broker/workspaces/{wid}/tasks/{task_id}/done` | x-broker-token | `backend/renewal/routers/v5.py:254` |
| **YES — was open** | POST | `/api/v5/cases/brief` | none (API key gate only) | `backend/renewal/routers/v5.py:343` |
| **YES — was open** | POST | `/api/v5/documents/statement` | none (API key gate only) | `backend/renewal/routers/v5.py:265` |
| **YES — was open** | POST | `/api/v5/leads` | none (API key gate only) | `backend/renewal/routers/v5.py:376` |
| **YES — was open** | GET | `/api/v5/leads/consent-text` | none (API key gate only) | `backend/renewal/routers/v5.py:371` |
| **YES — was open** | DELETE | `/api/v5/leads/{lead_id}` | none (API key gate only) | `backend/renewal/routers/v5.py:422` |
| **YES — was open** | GET | `/api/v5/rates/collection/status` | none (API key gate only) | `backend/renewal/main.py:560` |
| **YES — was open** | GET | `/api/v5/rates/posted` | none (API key gate only) | `backend/renewal/routers/v5.py:305` |
| **YES — was open** | GET | `/api/v5/rates/table` | none (API key gate only) | `backend/renewal/routers/v5.py:316` |
| **YES — was open** | GET | `/api/v5/rates/workbench-inputs` | none (API key gate only) | `backend/renewal/routers/v5.py:321` |
| had resource token | GET | `/api/v6/broker/workspaces/{wid}/renewal-tasks` | x-broker-token | `backend/renewal/main.py:593` |
| had resource token | POST | `/api/v6/broker/workspaces/{wid}/renewal-tasks/synchronize` | x-broker-token | `backend/renewal/main.py:577` |
| had resource token | PUT | `/api/v6/broker/workspaces/{wid}/renewal-tasks/{task_id}` | x-broker-token | `backend/renewal/main.py:609` |
| had resource token | GET | `/api/v6/broker/workspaces/{wid}/renewal-tasks/{task_id}/audit` | x-broker-token | `backend/renewal/main.py:621` |
| **YES — was open** | POST | `/api/v8/camera/inspect` | none (API key gate only) | `backend/renewal/main.py:789` |
| **YES — was open** | POST | `/api/v8/camera/ocr` | none (API key gate only) | `backend/renewal/main.py:1245` |
| **YES — was open** | POST | `/api/v8/camera/pdf` | none (API key gate only) | `backend/renewal/main.py:1267` |
| **YES — was open** | GET | `/api/v9/banking/institutions` | none (API key gate only) | `backend/renewal/main.py:682` |
| had resource token | GET | `/api/v9/broker/workspaces/{wid}/banking/events` | x-broker-token | `backend/renewal/main.py:773` |
| had resource token | POST | `/api/v9/broker/workspaces/{wid}/banking/sessions/{session_id}/exchange` | x-broker-token | `backend/renewal/main.py:698` |
| had resource token | GET | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/accounts` | x-broker-token | `backend/renewal/main.py:740` |
| had resource token | GET | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/cashflow` | x-broker-token | `backend/renewal/main.py:762` |
| had resource token | GET | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections` | x-broker-token | `backend/renewal/main.py:708` |
| had resource token | DELETE | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}` | x-broker-token | `backend/renewal/main.py:718` |
| had resource token | POST | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}/snapshot` | x-broker-token | `backend/renewal/main.py:728` |
| had resource token | GET | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/payment-evidence` | x-broker-token | `backend/renewal/main.py:750` |
| had resource token | POST | `/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/sessions` | x-broker-token | `backend/renewal/main.py:687` |
| no | GET | `/robots.txt` | PUBLIC allowlist | `backend/renewal/main.py:320` |
| no | GET | `/service-worker.js` | PUBLIC allowlist | `backend/renewal/main.py:315` |
| capability | GET | `/shared/{token}` | path token | `backend/renewal/main.py:333` |

## Line-by-line: routes that had no resource auth (now prod-gated)

1. `POST /api/agent/insight` — `backend/renewal/main.py:168` — `renewal.main.agent_insight`
1. `POST /api/agent/run` — `backend/renewal/main.py:177` — `renewal.main.agent_run`
1. `GET /api/agent/tools` — `backend/renewal/main.py:213` — `renewal.main.agent_tools`
1. `POST /api/analyze` — `backend/renewal/main.py:157` — `renewal.main.analyze`
1. `GET /api/calendar/{maturity_date}.ics` — `backend/renewal/main.py:257` — `renewal.main.calendar`
1. `POST /api/cases` — `backend/renewal/main.py:263` — `renewal.main.cases_create`
1. `GET /api/demo` — `backend/renewal/main.py:108` — `renewal.main.demo`
1. `GET /api/demo/sample-scan.png` — `backend/renewal/main.py:121` — `renewal.main.demo_scan`
1. `GET /api/demo/sample.pdf` — `backend/renewal/main.py:116` — `renewal.main.demo_pdf`
1. `POST /api/documents/extract` — `backend/renewal/main.py:125` — `renewal.main.pdf_extract`
1. `GET /api/health` — `backend/renewal/main.py:102` — `renewal.main.health`
1. `POST /api/ledger.csv` — `backend/renewal/main.py:238` — `renewal.main.export_ledger`
1. `POST /api/ledger/annual` — `backend/renewal/main.py:244` — `renewal.main.export_annual`
1. `GET /api/market` — `backend/renewal/main.py:223` — `renewal.main.market`
1. `GET /api/market/banks/live` — `backend/renewal/main.py:226` — `renewal.main.live_bank_rates`
1. `GET /api/market/discover` — `backend/renewal/main.py:231` — `renewal.main.market_discover`
1. `GET /api/market/lenders` — `backend/renewal/main.py:235` — `renewal.main.lenders`
1. `POST /api/negotiation` — `backend/renewal/main.py:220` — `renewal.main.negotiate`
1. `POST /api/penalty` — `backend/renewal/main.py:217` — `renewal.main.penalty`
1. `POST /api/penalty/v3/estimate` — `backend/renewal/main.py:357` — `renewal.main.penalty_v3_estimate`
1. `GET /api/penalty/v3/lenders` — `backend/renewal/main.py:347` — `renewal.main.penalty_v3_lenders`
1. `GET /api/penalty/v3/methods` — `backend/renewal/routers/v5.py:301` — `renewal.routers.v5.penalty_methods`
1. `POST /api/penalty/v3/workbench` — `backend/renewal/routers/v5.py:276` — `renewal.routers.v5.penalty_workbench`
1. `POST /api/penalty/v7/verify` — `backend/renewal/main.py:633` — `renewal.main.penalty_v7_verify`
1. `GET /api/policy` — `backend/renewal/main.py:301` — `renewal.main.policy`
1. `GET /api/ratewatch/backtest` — `backend/renewal/ratewatch/api.py:157` — `renewal.ratewatch.api.backtest_report`
1. `POST /api/ratewatch/extras/{tool}` — `backend/renewal/ratewatch/api.py:201` — `renewal.ratewatch.api.extras_endpoint`
1. `POST /api/ratewatch/forecast` — `backend/renewal/ratewatch/api.py:150` — `renewal.ratewatch.api.forecast_endpoint`
1. `POST /api/ratewatch/letter` — `backend/renewal/ratewatch/api.py:170` — `renewal.ratewatch.api.letter`
1. `GET /api/ratewatch/live` — `backend/renewal/ratewatch/api.py:232` — `renewal.ratewatch.api.live_board`
1. `POST /api/ratewatch/live/refresh` — `backend/renewal/ratewatch/api.py:238` — `renewal.ratewatch.api.live_refresh`
1. `POST /api/ratewatch/penalty` — `backend/renewal/ratewatch/api.py:144` — `renewal.ratewatch.api.penalty_endpoint`
1. `GET /api/ratewatch/rates/{lender}` — `backend/renewal/ratewatch/api.py:133` — `renewal.ratewatch.api.rates`
1. `POST /api/report/pdf` — `backend/renewal/main.py:248` — `renewal.main.report`
1. `POST /api/v10/ocr/fields` — `backend/renewal/main.py:937` — `renewal.main.ocr_fields`
1. `POST /api/v10/ocr/review` — `backend/renewal/main.py:945` — `renewal.main.ocr_review`
1. `GET /api/v11/mortgage/terms` — `backend/renewal/main.py:966` — `renewal.main.mortgage_terms`
1. `POST /api/v11/ocr/engine-plan` — `backend/renewal/main.py:959` — `renewal.main.ocr_engine_plan`
1. `GET /api/v11/ocr/engines` — `backend/renewal/main.py:955` — `renewal.main.ocr_engines`
1. `POST /api/v11/ocr/review-sessions` — `backend/renewal/main.py:1171` — `renewal.main.ocr_review_session_create`
1. `POST /api/v11/ocr/understand` — `backend/renewal/main.py:970` — `renewal.main.ocr_understand`
1. `POST /api/v12/contract-intelligence/answer` — `backend/renewal/main.py:992` — `renewal.main.contract_intelligence_answer`
1. `POST /api/v12/contract-intelligence/brief` — `backend/renewal/main.py:983` — `renewal.main.contract_intelligence_brief`
1. `POST /api/v12/contract-intelligence/playbook` — `backend/renewal/main.py:1006` — `renewal.main.contract_intelligence_playbook`
1. `GET /api/v12/contract-intelligence/sources` — `backend/renewal/main.py:979` — `renewal.main.contract_intelligence_sources`
1. `POST /api/v13/contract-intelligence/lender-packet` — `backend/renewal/main.py:1038` — `renewal.main.contract_lender_packet`
1. `POST /api/v13/contract-intelligence/math-audit` — `backend/renewal/main.py:1019` — `renewal.main.contract_math_audit`
1. `POST /api/v13/contract-intelligence/research-radar` — `backend/renewal/main.py:1028` — `renewal.main.contract_research_radar`
1. `GET /api/v13/contract-intelligence/research-sources` — `backend/renewal/main.py:1015` — `renewal.main.contract_research_sources`
1. `POST /api/v14/contract-intelligence/adapter-readiness` — `backend/renewal/main.py:1070` — `renewal.main.contract_adapter_readiness`
1. `POST /api/v14/contract-intelligence/dependency-plan` — `backend/renewal/main.py:1059` — `renewal.main.contract_dependency_plan`
1. `GET /api/v14/ocr/optional-dependencies` — `backend/renewal/main.py:1048` — `renewal.main.ocr_optional_dependencies`
1. `POST /api/v15/ocr/adapter-benchmark` — `backend/renewal/main.py:1132` — `renewal.main.ocr_adapter_benchmark`
1. `POST /api/v15/ocr/adapter-evaluate` — `backend/renewal/main.py:1095` — `renewal.main.ocr_adapter_evaluate`
1. `POST /api/v15/ocr/adapter-normalize` — `backend/renewal/main.py:1081` — `renewal.main.ocr_adapter_normalize`
1. `POST /api/v15/ocr/adapter-preview` — `backend/renewal/main.py:1088` — `renewal.main.ocr_adapter_preview`
1. `POST /api/v15/ocr/adapter-reconcile` — `backend/renewal/main.py:1118` — `renewal.main.ocr_adapter_reconcile`
1. `POST /api/v15/ocr/adapter-workbench` — `backend/renewal/main.py:1105` — `renewal.main.ocr_adapter_workbench`
1. `POST /api/v16/ocr/semantic-audit` — `backend/renewal/main.py:1146` — `renewal.main.document_semantic_audit`
1. `POST /api/v16/ocr/semantic-audit/pdf` — `backend/renewal/main.py:1157` — `renewal.main.document_semantic_pdf`
1. `POST /api/v17/documents/read` — `backend/renewal/main.py:140` — `renewal.main.document_read_v17`
1. `POST /api/v17/market/refresh` — `backend/renewal/main.py:329` — `renewal.main.live_market_refresh`
1. `GET /api/v17/market/snapshot` — `backend/renewal/main.py:324` — `renewal.main.live_market_snapshot`
1. `POST /api/v17/penalty/timeline` — `backend/renewal/main.py:353` — `renewal.main.penalty_v17_timeline`
1. `POST /api/v4/broker/workspaces` — `backend/renewal/main.py:504` — `renewal.main.create_broker_workspace`
1. `GET /api/v4/rates/historical-discount` — `backend/renewal/main.py:495` — `renewal.main.rate_historical_discount`
1. `GET /api/v4/rates/history` — `backend/renewal/main.py:483` — `renewal.main.rate_history`
1. `POST /api/v5/banklink/consents` — `backend/renewal/routers/v5.py:106` — `renewal.routers.v5.banklink_consent`
1. `DELETE /api/v5/banklink/consents/{cid}` — `backend/renewal/routers/v5.py:165` — `renewal.routers.v5.banklink_revoke`
1. `POST /api/v5/banklink/consents/{cid}/complete` — `backend/renewal/routers/v5.py:142` — `renewal.routers.v5.banklink_complete`
1. `POST /api/v5/banklink/consents/{cid}/session` — `backend/renewal/routers/v5.py:127` — `renewal.routers.v5.banklink_session`
1. `GET /api/v5/banklink/links/{link_id}/mortgages` — `backend/renewal/routers/v5.py:153` — `renewal.routers.v5.banklink_mortgages`
1. `GET /api/v5/banklink/providers` — `backend/renewal/routers/v5.py:98` — `renewal.routers.v5.banklink_providers`
1. `POST /api/v5/cases/brief` — `backend/renewal/routers/v5.py:343` — `renewal.routers.v5.cases_brief`
1. `POST /api/v5/documents/statement` — `backend/renewal/routers/v5.py:265` — `renewal.routers.v5.documents_statement`
1. `POST /api/v5/leads` — `backend/renewal/routers/v5.py:376` — `renewal.routers.v5.leads_create`
1. `GET /api/v5/leads/consent-text` — `backend/renewal/routers/v5.py:371` — `renewal.routers.v5.leads_consent_text`
1. `DELETE /api/v5/leads/{lead_id}` — `backend/renewal/routers/v5.py:422` — `renewal.routers.v5.leads_withdraw`
1. `GET /api/v5/rates/collection/status` — `backend/renewal/main.py:560` — `renewal.main.rate_collection_status`
1. `GET /api/v5/rates/posted` — `backend/renewal/routers/v5.py:305` — `renewal.routers.v5.rates_posted`
1. `GET /api/v5/rates/table` — `backend/renewal/routers/v5.py:316` — `renewal.routers.v5.rates_table`
1. `GET /api/v5/rates/workbench-inputs` — `backend/renewal/routers/v5.py:321` — `renewal.routers.v5.rates_workbench_inputs`
1. `POST /api/v8/camera/inspect` — `backend/renewal/main.py:789` — `renewal.main.camera_inspect`
1. `POST /api/v8/camera/ocr` — `backend/renewal/main.py:1245` — `renewal.main.camera_ocr`
1. `POST /api/v8/camera/pdf` — `backend/renewal/main.py:1267` — `renewal.main.camera_pdf`
1. `GET /api/v9/banking/institutions` — `backend/renewal/main.py:682` — `renewal.main.banking_institutions`

## Cross-tenant / capability risks (each needs review)

1. `POST /api/v5/leads` — `backend/renewal/routers/v5.py` (leads_create): workspace id existence check only; no broker token.
2. `POST /api/v5/banklink/consents` (+ session/complete/mortgages) — `routers/v5.py`: sandbox env flag only; subject is opaque string.
3. `POST /api/v4/broker/workspaces` — `main.py` create_broker_workspace: `RR_ENABLE_DEMO_WORKSPACES` flag, not identity.
4. `POST /api/cases` — `main.py` cases_create: returns access_token to anyone with API key.
5. `POST /api/v11/ocr/review-sessions` — `main.py` ocr_review_session_create: mints review token with no caller binding.
6. Broker `wid` path params — confirm every branch calls `_assert_access` / `broker_auth` (token header present).
7. `GET /api/shares/{share_token}` + `GET /shared/{token}` — capability URLs; token secrecy / rotation.
8. Legacy `GET /api/health` — not on public allowlist; only `/api/health/live` and `/ready` are.
9. `GET /api/v4/rates/history` + historical-discount — public market data historically; confirm OK behind API key only.
10. Ratewatch `/api/ratewatch/*` — previously fully open scrape/penalty surface.

## Batch 2 notes
- Legacy GET /api/health is public, body only {status:ok}; details on gated /ready.
- Leads create requires X-Broker-Token; prefer /broker/workspaces/{wid}/leads.

