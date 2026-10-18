"""HTTP surface for health probes and v5 product APIs expected by the test suite."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from ..security.uploads import ingest_document_upload
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..banklink.adapters import FlinksAdapter, PlaidAdapter, SandboxTransport
from ..banklink.models import CredentialRefused, Provider, Scope
from ..banklink.service import BankLinkService, ConsentError, to_renewal_inputs
from ..banklink.gateway import BankLinkGateway, COOKIE_NAME
from ..cases.tokens import case_tokens
from ..services import store as case_store
from ..broker.dashboard import BrokerDashboard
from ..broker.pipeline import InvalidTransition, Stage
from ..broker.workspace import AccessDenied, BrokerWorkspace
from ..cases.brief import ConfirmedFacts, build_brief
from ..documents.statement import read_statement
from ..documents.text import OcrUnavailable
from ..leads.consent import CONSENT_TEXTS, CURRENT_VERSION, ConsentInvalid, validate_consent
from ..leads.engine import LeadEngine, LeadInput
from ..leads.identity import Vault
from ..observability.health import readiness
from ..penalty.methods import all_specs
from ..penalty.workbench import WorkbenchCase, run_workbench
from ..rates.service import as_strings, reference_book, workbench_rates

D = Decimal
SANDBOX_DIR = Path(__file__).resolve().parents[1] / "banklink" / "sandbox"


def _dec(value: Any) -> D:
    try:
        return D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"invalid date: {value!r}") from exc


def _sandbox_service() -> BankLinkService:
    plaid = json.loads((SANDBOX_DIR / "plaid_sandbox.json").read_text(encoding="utf-8"))
    flinks = json.loads((SANDBOX_DIR / "flinks_sandbox.json").read_text(encoding="utf-8"))
    return BankLinkService({
        Provider.PLAID: PlaidAdapter(SandboxTransport(plaid)),
        Provider.FLINKS: FlinksAdapter(SandboxTransport(flinks)),
    })


def _require_banklink_sandbox() -> None:
    if os.environ.get("RR_ENABLE_BANKLINK_SANDBOX") != "1":
        raise HTTPException(403, "Bank-link sandbox is disabled")
    # Production fail-closed: no banklink traffic without a real RR_BANKLINK_KEY.
    # /api/v5/banklink/complete stays on the API-key public allowlist; this gate is separate.
    from ..banklink.crypto import BanklinkKeyError, require_production_banklink_key
    try:
        require_production_banklink_key()
    except BanklinkKeyError as exc:
        raise HTTPException(503, str(exc)) from exc


def _broker_or_404(ws: BrokerWorkspace, wid: str, token: str | None) -> None:
    try:
        ws._assert_access(wid, token or "")
    except AccessDenied as exc:
        raise HTTPException(404, "Workspace not found") from exc


def build_router(
    *,
    broker_workspace: BrokerWorkspace,
    broker_dashboard: BrokerDashboard,
    banklink_service: BankLinkService,
    banklink_gateway: BankLinkGateway,
    get_lead_engine: Callable[[], LeadEngine],
    frontend_check: Callable[[], object],
    case_store_check: Callable[[], object],
    connectors: Callable[[], dict[str, bool]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health/live")
    async def health_live():
        return {"status": "alive"}

    @router.get("/api/health/ready")
    async def health_ready():
        # Import late so tests can monkeypatch renewal.main._frontend_check.
        from renewal import main as main_mod
        report = readiness(
            [("case_store", case_store_check), ("frontend", main_mod._frontend_check)],
            connectors(),
        )
        status = 200 if report["status"] == "ready" else 503
        return JSONResponse(report, status_code=status)

    def _case_token_for(case_id: str, token: str | None, required: str):
        rec = case_tokens.verify(case_id, token, required=required)
        if rec is None:
            raise HTTPException(403, "Case token missing or insufficient scope")
        return rec

    @router.get("/api/v5/banklink/providers")
    async def banklink_providers():
        return {
            "providers": [p.value for p in banklink_service._adapters],
            "mode": "sandbox",
            "credential_collection": False,
        }

    @router.post("/api/v5/banklink/consents", status_code=201)
    async def banklink_consent(
        body: dict[str, Any],
        x_broker_token: str | None = Header(None),
        x_case_token: str | None = Header(None),
    ):
        """Bind consent to case/workspace. Broker of workspace OR case token banklink:connect."""
        _require_banklink_sandbox()
        case_id = str(body.get("case_id") or "")
        workspace_id = str(body.get("workspace_id") or "")
        if not case_id or not workspace_id:
            raise HTTPException(422, "case_id and workspace_id are required")
        meta = case_store.get_case_meta(case_id)
        if not meta or meta.get("workspace_id") != workspace_id:
            raise HTTPException(404, "Case not found")
        authorized = False
        if x_broker_token:
            try:
                broker_workspace._assert_access(workspace_id, x_broker_token)
                authorized = True
            except AccessDenied:
                pass
        if not authorized and x_case_token:
            if case_tokens.verify(case_id, x_case_token, required="banklink:connect") is not None:
                authorized = True
        if not authorized:
            raise HTTPException(403, "Broker or case token with banklink:connect required")
        try:
            consent = banklink_gateway.bind_consent(
                workspace_id=workspace_id,
                case_id=case_id,
                provider=Provider(str(body.get("provider") or "")),
                purpose=str(body.get("purpose") or ""),
                days=int(body.get("days") or 30),
                payload=body,
            )
        except (ConsentError, ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except CredentialRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "consent_id": consent.id,
            "expires_at": consent.expires_at.isoformat(),
            "case_id": case_id,
            "workspace_id": workspace_id,
        }

    @router.post("/api/v5/banklink/consents/{cid}/session")
    async def banklink_session(
        cid: str,
        body: dict[str, Any] | None = None,
        x_case_token: str | None = Header(None),
    ):
        """Borrower path: requires case token banklink:connect + PKCE S256 challenge."""
        _require_banklink_sandbox()
        body = body or {}
        binding = banklink_gateway.binding(cid)
        if binding is None:
            raise HTTPException(404, "Consent not found")
        _case_token_for(binding.case_id, x_case_token, "banklink:connect")
        code_challenge = str(body.get("code_challenge") or "")
        bind_cookie = bool(body.get("bind_cookie", True))
        try:
            session = banklink_gateway.start_session(
                cid, code_challenge=code_challenge, bind_cookie=bind_cookie
            )
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        headers = {}
        resp_body = {k: v for k, v in session.items() if k != "cookie_nonce"}
        response = JSONResponse(resp_body)
        if session.get("cookie_nonce"):
            response.set_cookie(
                COOKIE_NAME,
                session["cookie_nonce"],
                httponly=True,
                samesite="lax",
                max_age=900,
                path="/api/v5/banklink",
            )
        return response

    @router.post("/api/v5/banklink/complete")
    async def banklink_complete_public(request: Request, body: dict[str, Any]):
        """PUBLIC complete callback: one-time state + PKCE S256 + optional browser cookie.

        No X-Api-Key. Outer gate allowlists this path.
        """
        _require_banklink_sandbox()
        state = str(body.get("state") or "")
        code_verifier = str(body.get("code_verifier") or "")
        public_token = str(body.get("public_token") or "")
        cookie_nonce = request.cookies.get(COOKIE_NAME)
        if body.get("cookie_nonce"):
            cookie_nonce = str(body.get("cookie_nonce"))
        try:
            result = banklink_gateway.complete(
                state=state,
                code_verifier=code_verifier,
                public_token=public_token,
                cookie_nonce=cookie_nonce,
                payload=body,
            )
        except CredentialRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return result

    @router.post("/api/v5/banklink/consents/{cid}/complete")
    async def banklink_complete_legacy(cid: str, body: dict[str, Any], request: Request):
        """Deprecated path kept for migration; prefer POST /api/v5/banklink/complete."""
        _require_banklink_sandbox()
        # If state provided, delegate to public complete flow
        if body.get("state"):
            return await banklink_complete_public(request, body)
        raise HTTPException(
            410,
            "Use POST /api/v5/banklink/complete with state + code_verifier (PKCE). "
            "Direct consent complete is disabled.",
        )

    @router.get("/api/v5/banklink/links/{link_id}/mortgages")
    async def banklink_mortgages(
        link_id: str,
        x_broker_token: str | None = Header(None),
        x_case_token: str | None = Header(None),
    ):
        """Readable by same-workspace broker OR scoped case token banklink:read."""
        _require_banklink_sandbox()
        try:
            binding = banklink_gateway.authorize_link(link_id)
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        authorized = False
        if x_broker_token:
            try:
                broker_workspace._assert_access(binding.workspace_id, x_broker_token)
                authorized = True
            except AccessDenied:
                pass
        if not authorized and x_case_token:
            if case_tokens.verify(binding.case_id, x_case_token, required="banklink:read") is not None:
                authorized = True
            elif case_tokens.verify(binding.case_id, x_case_token, required="banklink:connect") is not None:
                authorized = True
        if not authorized:
            raise HTTPException(403, "Broker or case token required")
        try:
            snaps = banklink_service.mortgages(link_id)
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {
            "mortgages": [s.as_dict() for s in snaps],
            "prefill": [to_renewal_inputs(s) for s in snaps],
            "case_id": binding.case_id,
            "workspace_id": binding.workspace_id,
        }

    @router.delete("/api/v5/banklink/consents/{cid}", status_code=204)
    async def banklink_revoke(
        cid: str,
        x_broker_token: str | None = Header(None),
        x_case_token: str | None = Header(None),
    ):
        """Idempotent revoke: deletes tokens/data. Broker of workspace or case token."""
        _require_banklink_sandbox()
        binding = banklink_gateway.binding(cid)
        if binding is not None:
            authorized = False
            if x_broker_token:
                try:
                    broker_workspace._assert_access(binding.workspace_id, x_broker_token)
                    authorized = True
                except AccessDenied:
                    pass
            if not authorized and x_case_token:
                if case_tokens.verify(binding.case_id, x_case_token, required="banklink:connect") is not None:
                    authorized = True
            if not authorized:
                raise HTTPException(403, "Broker or case token required")
        banklink_gateway.revoke(cid)  # idempotent
        return Response(status_code=204)

    @router.get("/api/v5/broker/workspaces/{wid}/dashboard")
    async def broker_dashboard_summary(
        wid: str, top: int = Query(10, ge=1, le=100), x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            return broker_dashboard.summary(wid, x_broker_token or "", top=top)
        except AccessDenied as exc:
            raise HTTPException(404, "Workspace not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/v5/broker/workspaces/{wid}/clients/{cid}")
    async def broker_client_detail(wid: str, cid: str, x_broker_token: str | None = Header(None)):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            view = broker_dashboard.client(wid, x_broker_token or "", cid)
            view["history"] = broker_dashboard.history(wid, x_broker_token or "", cid)
            return view
        except AccessDenied as exc:
            raise HTTPException(404, "Client not found") from exc
        except KeyError as exc:
            raise HTTPException(404, "Client not found") from exc

    @router.patch("/api/v5/broker/workspaces/{wid}/clients/{cid}/profile")
    async def broker_client_profile(
        wid: str, cid: str, body: dict[str, Any], x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            return broker_dashboard.update_profile(
                wid,
                x_broker_token or "",
                cid,
                lender=body.get("lender"),
                balance=None if body.get("balance") is None else _dec(body["balance"]),
                rate_pct=None if body.get("rate_pct") is None else _dec(body["rate_pct"]),
                rate_type=body.get("rate_type"),
            )
        except AccessDenied as exc:
            raise HTTPException(404, "Client not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/v5/broker/workspaces/{wid}/clients/{cid}/stage")
    async def broker_client_stage(
        wid: str, cid: str, body: dict[str, Any], x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            stage = Stage(str(body.get("stage") or ""))
            return broker_dashboard.move(
                wid, x_broker_token or "", cid, stage, note=str(body.get("note") or "")
            )
        except (ValueError, InvalidTransition) as exc:
            raise HTTPException(422, str(exc)) from exc
        except AccessDenied as exc:
            raise HTTPException(404, "Client not found") from exc

    @router.post("/api/v5/broker/workspaces/{wid}/clients/{cid}/tasks", status_code=201)
    async def broker_add_task(
        wid: str, cid: str, body: dict[str, Any], x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            return broker_dashboard.add_task(
                wid,
                x_broker_token or "",
                cid,
                str(body.get("kind") or ""),
                str(body.get("title") or ""),
                _day(body.get("due")),
            )
        except AccessDenied as exc:
            # Consent missing or wrong tenant — tests expect 403 for consent, 404 for tenant.
            msg = str(exc).lower()
            raise HTTPException(403 if "consent" in msg else 404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/v5/broker/workspaces/{wid}/tasks/{task_id}/done", status_code=204)
    async def broker_complete_task(
        wid: str, task_id: str, x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            broker_dashboard.complete_task(wid, x_broker_token or "", task_id)
        except AccessDenied as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(status_code=204)

    @router.post("/api/v5/documents/statement")
    async def documents_statement(file: UploadFile = File(...)):
        try:
            ingested = await ingest_document_upload(file)
            reading = read_statement(ingested.data)
        except OcrUnavailable as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()
        return reading.as_dict()

    @router.post("/api/penalty/v3/workbench")
    async def penalty_workbench(body: dict[str, Any]):
        try:
            posted = body.get("current_posted") or {}
            case = WorkbenchCase(
                lender=str(body.get("lender") or ""),
                balance=_dec(body.get("balance")),
                contract_rate=_dec(body.get("contract_rate")),
                term_start=_day(body.get("term_start")),
                maturity=_day(body.get("maturity")),
                payout=_day(body.get("payout")),
                current_posted={int(k): _dec(v) for k, v in posted.items()},
                original_posted_rate=(
                    None if body.get("original_posted_rate") is None else _dec(body["original_posted_rate"])
                ),
                contract_discount=(
                    None if body.get("contract_discount") is None else _dec(body["contract_discount"])
                ),
                cashback=_dec(body["cashback"]) if body.get("cashback") is not None else D("0"),
                is_open=bool(body.get("is_open") or False),
            )
            return run_workbench(case).as_dict()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/penalty/v3/methods")
    async def penalty_methods():
        return {"methods": all_specs()}

    @router.get("/api/v5/rates/posted")
    async def rates_posted(
        lender: str = Query(...),
        term_months: int = Query(..., ge=1, le=120),
        on: str = Query(...),
    ):
        hit = reference_book().posted_at(lender, term_months, _day(on), allow_proxy=False)
        if hit is None:
            raise HTTPException(404, "No posted observation for that lender/term/date")
        return hit.as_dict()

    @router.get("/api/v5/rates/table")
    async def rates_table(lender: str = Query(...), on: str = Query(...)):
        table = reference_book().table_at(lender, _day(on))
        return {"lender": lender.lower(), "on": on, "table": {str(k): v.as_dict() for k, v in table.items()}}

    @router.get("/api/v5/rates/workbench-inputs")
    async def rates_workbench_inputs(
        lender: str = Query(...),
        funded: str = Query(...),
        payout: str = Query(...),
        term_months: int = Query(60, ge=1, le=120),
    ):
        try:
            funding, pay = _day(funded), _day(payout)
            if pay < funding:
                raise ValueError("payout must be on or after funding")
            raw = workbench_rates(reference_book(), lender, funding, pay, term_months)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "original_posted_rate": None if raw["original_posted_rate"] is None else str(raw["original_posted_rate"]),
            "original_evidence": raw["original_evidence"],
            "current_posted": as_strings(raw["current_posted"]),
            "current_evidence": raw["current_evidence"],
            "uses_proxy": raw["uses_proxy"],
        }

    @router.post("/api/v5/cases/brief")
    async def cases_brief(body: dict[str, Any], as_of: str | None = None):
        try:
            rate_type = str(body.get("rate_type") or "fixed")
            if rate_type not in ("fixed", "variable"):
                raise ValueError("rate_type must be fixed or variable")
            facts = ConfirmedFacts(
                lender=str(body.get("lender") or ""),
                balance=_dec(body.get("balance")),
                rate_pct=_dec(body.get("rate_pct")),
                maturity_date=_day(body.get("maturity_date")),
                term_months=int(body.get("term_months")),
                amortization_months=(
                    None if body.get("amortization_months") is None else int(body["amortization_months"])
                ),
                renewal_rate_pct=(
                    None if body.get("renewal_rate_pct") is None else _dec(body["renewal_rate_pct"])
                ),
                rate_type=rate_type,
                contract_discount=(
                    None if body.get("contract_discount") is None else _dec(body["contract_discount"])
                ),
            )
            today = _day(as_of) if as_of else date.today()
            return build_brief(facts, reference_book(), today).as_dict()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/v5/leads/consent-text")
    async def leads_consent_text():
        text = CONSENT_TEXTS[CURRENT_VERSION]
        return {"version": text.version, "digest": text.digest, "text": text.text}

    def _lead_from_body(wid: str, body: dict[str, Any]) -> LeadInput:
        """Build LeadInput from the client body. Never trusts client id/status/created_by."""
        # Drop client-supplied identity / lifecycle fields (server owns these).
        for banned in ("id", "status", "created_by", "workspace_id", "withdraw_token"):
            body.pop(banned, None)
        consent_body = body.get("consent") or {}
        agreed_at = datetime.fromisoformat(str(consent_body.get("agreed_at")).replace("Z", "+00:00"))
        consent = validate_consent(
            version=str(consent_body.get("version") or ""),
            text_digest=str(consent_body.get("text_digest") or ""),
            agreed=consent_body.get("agreed"),
            agreed_at=agreed_at,
            contact_methods=list(consent_body.get("contact_methods") or []),
            brokerage=str(consent_body.get("brokerage") or ""),
            now=datetime.now(agreed_at.tzinfo),
        )
        return LeadInput(
            workspace_id=wid,
            name=str(body.get("name") or ""),
            email=body.get("email"),
            phone=body.get("phone"),
            province=str(body.get("province") or ""),
            consent=consent,
            renewal_date=None if body.get("renewal_date") is None else _day(body["renewal_date"]),
            balance=None if body.get("balance") is None else _dec(body["balance"]),
            current_rate=None if body.get("current_rate") is None else _dec(body["current_rate"]),
            market_rate=None if body.get("market_rate") is None else _dec(body["market_rate"]),
            has_statement=bool(body.get("has_statement") or False),
            completed_analysis=bool(body.get("completed_analysis") or False),
        )

    def _create_lead_for_workspace(wid: str, token: str | None, body: dict[str, Any]) -> dict:
        """Authorize broker membership, then create. created_by is the workspace principal.

        Temporary until OIDC/workspace SSO: X-Broker-Token is the principal, matching
        other /api/v5/broker/workspaces/{wid}/* routes.
        """
        _broker_or_404(broker_workspace, wid, token)
        try:
            payload = dict(body or {})
            lead = _lead_from_body(wid, payload)
            created = get_lead_engine().submit(lead)
        except ConsentInvalid as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            if "not configured" in str(exc).lower() or "key" in str(exc).lower():
                raise HTTPException(503, str(exc)) from exc
            raise
        with broker_workspace._db() as db:
            broker_workspace._audit(
                db, wid, None, "lead_created",
                {"lead_id": created.get("id"), "created_by": wid, "duplicate": bool(created.get("duplicate"))},
            )
        created = dict(created)
        created["created_by"] = wid
        return created

    @router.post("/api/v5/broker/workspaces/{wid}/leads", status_code=201)
    async def broker_create_lead(
        wid: str, body: dict[str, Any], x_broker_token: str | None = Header(None)
    ):
        """Canonical lead create: workspace is the path id; broker token required."""
        return _create_lead_for_workspace(wid, x_broker_token, body)

    @router.post("/api/v5/leads", status_code=201)
    async def leads_create_legacy(body: dict[str, Any], x_broker_token: str | None = Header(None)):
        """Legacy path — still requires X-Broker-Token; ignores client workspace spoofing.

        Prefer POST /api/v5/broker/workspaces/{wid}/leads. Body workspace_id is only used
        after membership is verified for that same id.
        """
        wid = str(body.get("workspace_id") or "")
        if not wid:
            raise HTTPException(422, "workspace_id is required on the legacy path")
        return _create_lead_for_workspace(wid, x_broker_token, body)

    @router.delete("/api/v5/leads/{lead_id}", status_code=204)
    async def leads_withdraw(
        lead_id: str,
        body: dict[str, Any] | None = None,
        x_broker_token: str | None = Header(None),
    ):
        """Withdraw/delete a lead. Workspace comes from the DB row, never the client.

        Auth: homeowner withdraw_token (capability) OR X-Broker-Token for that workspace.
        Failures return 404 so existence is not confirmed to strangers.
        """
        engine = get_lead_engine()
        with engine._db() as db:
            row = db.execute(
                "SELECT id, workspace_id, status FROM leads WHERE id=?", (lead_id,)
            ).fetchone()
        if row is None or row["status"] == "withdrawn":
            raise HTTPException(404, "Not Found")
        wid = row["workspace_id"]
        body = body or {}
        withdraw_token = str(body.get("withdraw_token") or "")
        authorized = False
        if withdraw_token:
            try:
                engine.withdraw(lead_id, withdraw_token)
                authorized = True
            except PermissionError:
                authorized = False
        if not authorized and x_broker_token:
            try:
                broker_workspace._assert_access(wid, x_broker_token)
                # Broker-authorized delete uses the stored withdraw digest path via a
                # controlled erase: reuse withdraw only when token known; else direct erase.
                with engine._lock, engine._db() as db:
                    db.execute(
                        "UPDATE leads SET status='withdrawn', contact_sealed=NULL WHERE id=? AND workspace_id=?",
                        (lead_id, wid),
                    )
                    db.execute("DELETE FROM lead_keys WHERE lead_id=?", (lead_id,))
                authorized = True
            except AccessDenied:
                authorized = False
        if not authorized:
            raise HTTPException(404, "Not Found")
        with broker_workspace._db() as db:
            broker_workspace._audit(
                db, wid, None, "lead_withdrawn",
                {"lead_id": lead_id, "by": "withdraw_token" if withdraw_token else "broker"},
            )
        return Response(status_code=204)

    @router.get("/api/v5/broker/workspaces/{wid}/leads")
    async def broker_list_leads(wid: str, x_broker_token: str | None = Header(None)):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        return {"leads": get_lead_engine().for_broker(wid)}

    @router.post("/api/v5/broker/workspaces/{wid}/leads/{lead_id}/reveal")
    async def broker_reveal_lead(
        wid: str, lead_id: str, x_broker_token: str | None = Header(None)
    ):
        _broker_or_404(broker_workspace, wid, x_broker_token)
        try:
            contact = get_lead_engine().reveal(wid, lead_id)
        except PermissionError as exc:
            raise HTTPException(404, str(exc)) from exc
        with broker_workspace._db() as db:
            broker_workspace._audit(db, wid, None, "lead_contact_revealed", {"lead_id": lead_id})
        return {"contact": contact}

    return router
