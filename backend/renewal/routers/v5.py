"""HTTP surface for health probes and v5 product APIs expected by the test suite."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..banklink.adapters import FlinksAdapter, PlaidAdapter, SandboxTransport
from ..banklink.models import CredentialRefused, Provider, Scope
from ..banklink.service import BankLinkService, ConsentError, to_renewal_inputs
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

    @router.get("/api/v5/banklink/providers")
    async def banklink_providers():
        return {
            "providers": [p.value for p in banklink_service._adapters],
            "mode": "sandbox",
            "credential_collection": False,
        }

    @router.post("/api/v5/banklink/consents", status_code=201)
    async def banklink_consent(body: dict[str, Any]):
        _require_banklink_sandbox()
        try:
            scopes = {Scope.MORTGAGE_READ}
            if body.get("scopes"):
                scopes = {Scope(s) for s in body["scopes"]}
            consent = banklink_service.grant(
                str(body.get("subject") or ""),
                Provider(str(body.get("provider") or "")),
                scopes,
                str(body.get("purpose") or ""),
                days=int(body.get("days") or 30),
                payload=body,
            )
        except (ConsentError, ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except CredentialRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"consent_id": consent.id, "expires_at": consent.expires_at.isoformat()}

    @router.post("/api/v5/banklink/consents/{cid}/session")
    async def banklink_session(cid: str):
        _require_banklink_sandbox()
        try:
            session = banklink_service.start(cid)
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {
            "provider": session.provider.value,
            "link_token": session.link_token,
            "widget_url": session.widget_url,
            "expires_at": session.expires_at.isoformat(),
            "sandbox": session.sandbox,
        }

    @router.post("/api/v5/banklink/consents/{cid}/complete")
    async def banklink_complete(cid: str, body: dict[str, Any]):
        _require_banklink_sandbox()
        try:
            link_id = banklink_service.complete(cid, str(body.get("public_token") or ""), body)
        except CredentialRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {"link_id": link_id}

    @router.get("/api/v5/banklink/links/{link_id}/mortgages")
    async def banklink_mortgages(link_id: str):
        _require_banklink_sandbox()
        try:
            snaps = banklink_service.mortgages(link_id)
        except ConsentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {
            "mortgages": [s.as_dict() for s in snaps],
            "prefill": [to_renewal_inputs(s) for s in snaps],
        }

    @router.delete("/api/v5/banklink/consents/{cid}", status_code=204)
    async def banklink_revoke(cid: str):
        _require_banklink_sandbox()
        try:
            banklink_service.revoke(cid)
        except ConsentError as exc:
            raise HTTPException(404, str(exc)) from exc
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
        data = await file.read()
        try:
            reading = read_statement(data)
        except OcrUnavailable as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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

    @router.post("/api/v5/leads", status_code=201)
    async def leads_create(body: dict[str, Any]):
        wid = str(body.get("workspace_id") or "")
        # Unknown workspaces must 404 (no existence leak via other codes).
        with broker_workspace._db() as db:
            row = db.execute("SELECT id FROM broker_workspaces WHERE id=?", (wid,)).fetchone()
        if row is None:
            raise HTTPException(404, "Workspace not found")
        try:
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
            lead = LeadInput(
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
            return get_lead_engine().submit(lead)
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

    @router.delete("/api/v5/leads/{lead_id}", status_code=204)
    async def leads_withdraw(lead_id: str, body: dict[str, Any]):
        try:
            get_lead_engine().withdraw(lead_id, str(body.get("withdraw_token") or ""))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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
