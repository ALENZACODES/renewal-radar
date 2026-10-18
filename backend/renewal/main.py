"""Renewal Radar HTTP API and built-in commercial-style web UI.

Run: PYTHONPATH=backend uvicorn renewal.main:app --reload
Open: http://127.0.0.1:8000
"""
from __future__ import annotations
import os,sys,json,logging
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date,datetime,timezone
from fastapi import FastAPI,HTTPException,UploadFile,File,Body,Header,Query,Depends
from fastapi.responses import JSONResponse,Response,FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from .security.rate_limit import SlidingWindowLimiter
from pydantic import ValidationError
from .config import settings
from .security.access import require_api_access, demo_enabled, demo_samples_allowed, is_production
from .security.log_redact import install_log_redaction
from .banklink.crypto import require_production_banklink_key
from .security.uploads import ingest_document_upload, read_upload_capped, MAX_UPLOAD_BYTES
from .domain.schemas import AnalyzeRequest,Mortgage,Offer,PenaltyRequest,CaseCreate,CaseTokenMint,ShareRequest,NegotiationRequest
from .domain.mortgage_math import compare_offers,stress_paths,simulate
from .domain.rules import mqr,switch_decision,penalty_estimate,OSFI_MQR,OSFI_SWITCH,RENEWAL
from .services.extract import extract_pdf
from .services.document_ocr_v17 import read_mortgage_document
from .ocr.camera import CameraError
from .ocr.engines import OCREngineError
from .services.market import fetch_boc,bank_catalog
from .services.market_tracker_v17 import LiveRateTracker
from .services.agent import explain,enrich_extraction,TOOLS
from .services.negotiation import negotiation_packet
from .services.plan import make_plan,create_ics
from .services.report import render_report
from .services.ledger import ledger_csv,annual_summary
from .services import store
from .providers.bank_rates import fetch_bank_posted_rates
from .providers.tavily import discover

ROOT=Path(__file__).resolve().parents[2]
FRONTEND=ROOT/'frontend'
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger('renewal_radar')

@asynccontextmanager
async def lifespan(app:FastAPI):
    install_log_redaction()
    require_production_banklink_key()  # fail closed: no weak/missing RR_BANKLINK_KEY in production
    store.initialize()
    app.state.live_rate_tracker = LiveRateTracker()
    app.state.live_rate_tracker.start()
    try:
        yield
    finally:
        await app.state.live_rate_tracker.stop()

app=FastAPI(title='Renewal Radar 2.0',version='2.0.0',
    description='Canadian mortgage renewal analysis, source-backed rule engine, privacy-conscious agent and PDF reports',lifespan=lifespan,
    dependencies=[Depends(require_api_access)])
from .ratewatch.api import router as ratewatch_router
app.include_router(ratewatch_router)
from .broker.book_api import router as broker_book_router
app.include_router(broker_book_router)
app.add_middleware(CORSMiddleware,allow_origins=list(settings.allowed_origins),allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-Case-Token','X-Broker-Token','X-Rate-Ingest-Key','X-OCR-Review-Token','X-Api-Key'])

limiter = SlidingWindowLimiter()


@app.middleware('http')
async def enforce_rate_limits(request, call_next):
    """Apply in-process sliding-window limits using the direct client address."""
    client = request.client.host if request.client else 'unknown'
    decision = limiter.check(client, request.url.path)
    if decision is None:
        return await call_next(request)
    if not decision.allowed:
        retry = max(1, int(decision.retry_after + 0.999))
        return JSONResponse(
            {'detail': 'Rate limit exceeded. Try again shortly.'},
            status_code=429,
            headers={
                'Retry-After': str(retry),
                'X-RateLimit-Limit': str(decision.limit),
                'X-RateLimit-Remaining': '0',
                'X-Content-Type-Options': 'nosniff',
            },
        )
    response = await call_next(request)
    response.headers['X-RateLimit-Limit'] = str(decision.limit)
    response.headers['X-RateLimit-Remaining'] = str(decision.remaining)
    return response


@app.middleware('http')
async def add_security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']=(
       "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.get('/api/health')
async def health():
    # Public liveness-shaped probe only. Detailed checks live on /api/health/ready (gated).
    return {'status': 'ok'}

@app.get('/api/demo')
async def demo():
    if not demo_samples_allowed():
        raise HTTPException(404, 'Not Found')
    return {'mortgage':Mortgage().model_dump(),
       'offers':[Offer(name='Illustrative alternative',rate=4.49,rate_type='fixed',term_months=36,type='hypothetical',fees=950).model_dump(),
                 Offer(name='Illustrative variable',rate=4.25,rate_type='variable',term_months=36,type='hypothetical',fees=1100).model_dump()],
       'case_title':'Sample renewal: $480,000 balance',
       'notice':'RBC Royal Bank demonstration using hypothetical terms. Not issued or endorsed by RBC; no rates are verified borrower quotes.'}

@app.get('/api/demo/sample.pdf')
async def demo_pdf():
    if not demo_samples_allowed():
        raise HTTPException(404, 'Not Found')
    return FileResponse(ROOT/'fixtures'/'fictional-renewal-letter.pdf',media_type='application/pdf',headers={'Cache-Control':'no-store'})


@app.get('/api/demo/sample-scan.png')
async def demo_scan():
    if not demo_samples_allowed():
        raise HTTPException(404, 'Not Found')
    return FileResponse(ROOT/'fixtures'/'rbc-renewal-scan.png', media_type='image/png', headers={'Cache-Control': 'no-store'})

@app.post('/api/documents/extract')
async def pdf_extract(file: UploadFile=File(...)):
    try:
        ingested = await ingest_document_upload(
            file, max_bytes=min(settings.max_pdf_bytes, MAX_UPLOAD_BYTES), allowed={'pdf'})
    finally:
        await file.close()
    try:
        extracted=extract_pdf(ingested.data, ingested.filename)
        extracted=await enrich_extraction(extracted)
        return extracted.model_dump()
    except ValueError as exc:raise HTTPException(422,str(exc))


@app.post('/api/v17/documents/read')
async def document_read_v17(file: UploadFile = File(...), language: str = Query(default='eng', pattern=r'^(eng|fra|eng\+fra)$')):
    from starlette.concurrency import run_in_threadpool
    try:
        ingested = await ingest_document_upload(file, max_bytes=MAX_UPLOAD_BYTES, allowed={'pdf', 'png', 'jpeg'})
        return await run_in_threadpool(read_mortgage_document, ingested.data, ingested.filename, language)
    except OCREngineError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, CameraError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()

@app.post('/api/analyze')
async def analyze(body:AnalyzeRequest):
    output=compare_offers(body.mortgage,body.offers,body.horizon_months,body.discount_rate)
    output['switch']=switch_decision(body.mortgage,body.offers[0].rate if body.offers else body.mortgage.offered_rate)
    output['stress']=stress_paths(body.mortgage,horizon_months=body.horizon_months)
    output['plan']=make_plan(body.mortgage.maturity_date)
    output['audit']={'math':'RR-MATH-v2.0','policy':'CAN-MQR-2026.10',
      'input_rates_are_user_supplied':True,'as_of':datetime.now(timezone.utc).isoformat(),
      'regulatory_sources':[OSFI_MQR,OSFI_SWITCH,RENEWAL]}
    return output

@app.post('/api/agent/insight')
async def agent_insight(body:AnalyzeRequest):
    comparison=compare_offers(body.mortgage,body.offers,body.horizon_months)
    switch=switch_decision(body.mortgage)
    best=next((s for s in comparison['scenarios'][1:] if s['vs_renewal']['net_benefit']>0),None)
    return await explain({'balance':body.mortgage.balance,'renewal_rate':body.mortgage.offered_rate,
       'benefit':best['vs_renewal']['net_benefit'] if best else None,
       'switch_status':switch['status'],'all_market_quotes_hypothetical':all(o.type=='hypothetical' for o in body.offers)})

@app.post('/api/agent/run')
async def agent_run(body:AnalyzeRequest):
    """One request orchestrates verified-source, rules, math and language tools.

    Document extraction is a separately authenticated-by-user upload step;
    PDF text is not retained or exposed through this endpoint.
    """
    steps=[]
    def event(tool,summary,source=None):
        steps.append({'order':len(steps)+1,'tool':tool,'result':summary,'source':source,
          'timestamp':datetime.now(timezone.utc).isoformat(),'status':'complete'})
    event('validate_input','Verified numeric ranges, term limits and required mortgage fields.')
    market=await fetch_boc()
    event('get_verified_market','Bank of Canada feed: '+market['data_status'],market['source_url'])
    switch=switch_decision(body.mortgage,body.offers[0].rate if body.offers else None)
    event('classify_switch',switch['headline'],switch['sources'][0])
    comp=compare_offers(body.mortgage,body.offers,body.horizon_months,body.discount_rate)
    event('compare_offers',str(len(comp['scenarios']))+' modelled choices over a shared time horizon.')
    stress=stress_paths(body.mortgage,horizon_months=body.horizon_months)
    event('stress_paths',str(len(stress['paths']))+' independently modelled variable-rate trajectories.')
    negotiation=negotiation_packet(NegotiationRequest(mortgage=body.mortgage,
       competing_rate=body.offers[0].rate if body.offers else body.mortgage.offered_rate))
    event('build_negotiation','Personalized call script and lender-specific questions prepared.')
    plan=make_plan(body.mortgage.maturity_date)
    event('build_action_plan',str(len(plan))+' dated renewal tasks generated.',RENEWAL)
    best=next((s for s in comp['scenarios'][1:] if s['vs_renewal']['net_benefit']>0),None)
    explanation=await explain({'benefit':best['vs_renewal']['net_benefit'] if best else None,
        'switch_status':switch['status'],'modelled_quotes_are_not_verified_market_offers':True})
    event('nemotron_explain' if explanation['enabled'] else 'rule_explain',explanation['provider']+' plain-language explanation.')
    return {'steps':steps,'summary':explanation,'switch':switch,
      'comparison':{'best_name':comp['best_name'],'scenarios':[{
        'name':s['offer']['name'],'net_benefit':s['vs_renewal']['net_benefit'],
        'assumption_type':s['offer']['type']} for s in comp['scenarios']]},
      'market':{'status':market['data_status'],'checked_at':market['checked_at']},
      'notice':'All calculation and policy outputs are deterministic. Uploaded PDF bytes are not saved.'}

@app.get('/api/agent/tools')
async def agent_tools():return {'tools':TOOLS,'ai_configured':bool(settings.nebius_api_key),
   'policy':'All calculations and switching decisions run deterministically; the optional model only explains validated results.'}

@app.post('/api/penalty')
async def penalty(body:PenaltyRequest):return penalty_estimate(**body.model_dump())

@app.post('/api/negotiation')
async def negotiate(body:NegotiationRequest):return negotiation_packet(body)

@app.get('/api/market')
async def market():return await fetch_boc()

@app.get('/api/market/banks/live')
async def live_bank_rates():
    return {'bank_rates':await fetch_bank_posted_rates(),
            'notice':'Only unambiguous product-specific 5-year fixed posted HTML rates are promoted; otherwise links are supplied without numeric quotes.'}

@app.get('/api/market/discover')
async def market_discover(query:str=Query(default='Canada mortgage posted fixed rates official bank',max_length=300)):
    return await discover(query)

@app.get('/api/market/lenders')
async def lenders():return {'data':bank_catalog(),'notice':'Links are official bank sources, not scraped or verified quotes.'}

@app.post('/api/ledger.csv')
async def export_ledger(body:AnalyzeRequest):
    return Response(ledger_csv(body),media_type='text/csv; charset=utf-8',
      headers={'Content-Disposition':'attachment; filename="renewal-radar-amortization.csv"',
               'Cache-Control':'no-store'})

@app.post('/api/ledger/annual')
async def export_annual(body:AnalyzeRequest):
    return annual_summary(body)

@app.post('/api/report/pdf')
async def report(body:AnalyzeRequest):
    analysis=compare_offers(body.mortgage,body.offers,body.horizon_months,body.discount_rate)
    switch=switch_decision(body.mortgage)
    penalty=penalty_estimate(**body.penalty.model_dump()) if body.penalty else None
    pdf=render_report(body.mortgage,analysis,switch,penalty)
    return Response(pdf,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="renewal-radar-strategy.pdf"',
      'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get('/api/calendar/{maturity_date}.ics')
async def calendar(maturity_date:str):
    try:data=create_ics(maturity_date)
    except ValueError:raise HTTPException(422,'Invalid maturity date')
    return Response(data,media_type='text/calendar',headers={'Content-Disposition':'attachment; filename="renewal-radar-reminders.ics"','Cache-Control':'no-store'})

@app.post('/api/cases',status_code=201)
async def cases_create(body:CaseCreate,x_broker_token:str|None=Header(default=None)):
    """Broker-owned case create. Returns case id only — no long-lived access token.

    Mint scoped tokens via POST /api/cases/{id}/tokens (broker principal required).
    """
    from .broker.workspace import AccessDenied as _AD
    try:
        broker_workspace._assert_access(body.workspace_id, x_broker_token or '')
    except _AD:
        raise HTTPException(404, 'Workspace not found')
    return store.create_case(
        body.title,
        {'mortgage': body.mortgage.model_dump(), 'offers': [o.model_dump() for o in body.offers]},
        workspace_id=body.workspace_id,
        mint_legacy_token=False,
    )

def access_or_404(uid,token):
    obj=store.read_case(uid,token)
    if not obj:raise HTTPException(404,'Case not found or access token invalid')
    return obj

@app.post('/api/cases/{uid}/tokens',status_code=201)
async def cases_mint_token(
    uid: str,
    body: CaseTokenMint,
    x_broker_token: str | None = Header(default=None),
):
    """Mint a hashed, scoped, TTL case token. Broker of the owning workspace only.

    API-key-only callers cannot mint. Email OTP binding for borrower invites is TODO.
    """
    from .broker.workspace import AccessDenied as _AD
    from .cases.tokens import case_tokens
    meta = store.get_case_meta(uid)
    if not meta or not meta.get('workspace_id'):
        raise HTTPException(404, 'Case not found')
    try:
        broker_workspace._assert_access(meta['workspace_id'], x_broker_token or '')
    except _AD:
        raise HTTPException(404, 'Case not found')
    try:
        minted = case_tokens.mint(
            case_id=uid,
            workspace_id=meta['workspace_id'],
            scopes=body.scopes,
            ttl_seconds=body.ttl_seconds,
        )
    except PermissionError as exc:
        raise HTTPException(429, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # TODO: email OTP verification before handing token to borrower if invite flow is enabled
    return minted

@app.get('/api/cases/{uid}')
async def cases_get(uid:str,x_case_token:str|None=Header(default=None)):
    return access_or_404(uid,x_case_token)

@app.put('/api/cases/{uid}')
async def cases_update(uid:str,body:CaseCreate,x_case_token:str|None=Header(default=None)):
    access_or_404(uid,x_case_token)
    result=store.update_case(uid,x_case_token,{'mortgage':body.mortgage.model_dump(),
               'offers':[o.model_dump() for o in body.offers]})
    return {'saved':result}

@app.post('/api/cases/{uid}/share',status_code=201)
async def shares_create(uid:str,body:ShareRequest,x_case_token:str|None=Header(default=None)):
    access_or_404(uid,x_case_token)
    result=store.create_share(uid,x_case_token,body.expires_hours)
    if not result:raise HTTPException(404,'Case not found')
    return {**result,'url_path':'/shared/'+result['token']}

@app.get('/api/shares/{share_token}')
async def shares_get(share_token:str):
    obj=store.read_share(share_token)
    if not obj:raise HTTPException(404,'Link revoked, invalid or expired')
    return obj

@app.delete('/api/cases/{uid}/shares/{share_token}')
async def shares_revoke(uid:str,share_token:str,x_case_token:str|None=Header(default=None)):
    access_or_404(uid,x_case_token)
    return {'revoked':store.revoke_share(uid,x_case_token,share_token)}

@app.get('/api/policy')
async def policy():
    return {'effective_context':'2026-10','minimum_qualifying_rate_floor':5.25,
      'minimum_qualifying_rate_buffer_pp':2.0,'straight_switch_effective':'2024-11-21',
      'uninsured_switch':{'conditions':['Existing stand-alone non-readvanceable uninsured residential mortgage',
          'Both lenders federally regulated','No equity withdrawal or greater remaining amortization',
          'Up to $3,000 additional principal solely for eligible transaction costs'],
          'source':OSFI_SWITCH},
      'standard_mqr':'max(contract_rate + 2.00 percentage points, 5.25%)',
      'source':OSFI_MQR}

@app.get('/')
async def homepage():return FileResponse(FRONTEND/'index.html')

@app.get('/service-worker.js')
async def offline_service_worker():
    return FileResponse(FRONTEND / 'service-worker.js', media_type='application/javascript',
                        headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})

@app.get('/robots.txt')
async def crawler_rules():
    return FileResponse(FRONTEND / 'robots.txt', media_type='text/plain')

@app.get('/api/v17/market/snapshot')
async def live_market_snapshot():
    tracker = app.state.live_rate_tracker
    return tracker.snapshot() if tracker.snapshot()['revision'] else await tracker.refresh()

@app.post('/api/v17/market/refresh')
async def live_market_refresh():
    return await app.state.live_rate_tracker.refresh()

@app.get('/shared/{token}')
async def shared_page(token:str):return FileResponse(FRONTEND/'index.html')

app.mount('/assets',StaticFiles(directory=FRONTEND/'assets'),name='assets')
app.mount('/js',StaticFiles(directory=FRONTEND/'js'),name='js')

# Transparent lender-profiled penalty API. Kept separate from the legacy
# approximation endpoint for backward compatibility with existing clients.
from .penalty import PenaltyInputs as DetailedPenaltyInputs, calculate_penalty as detailed_penalty
from .penalty.profiles import lender_profiles as detailed_lender_profiles
from .services.penalty_timeline_v17 import PenaltyTimelineRequest, penalty_timeline
from decimal import Decimal
from typing import Any

@app.get('/api/penalty/v3/lenders')
async def penalty_v3_lenders():
    return {'lenders': detailed_lender_profiles(),
      'warning':'A published method profile is not a guarantee of a lender-exact payout quote.'}


@app.post('/api/v17/penalty/timeline')
def penalty_v17_timeline(payload: PenaltyTimelineRequest):
    return penalty_timeline(payload)

@app.post('/api/penalty/v3/estimate')
async def penalty_v3_estimate(payload: dict[str, Any]):
    """Values are decimal strings; preserves cents without float conversion."""
    from dataclasses import fields
    from .penalty.models import Method
    from typing import get_type_hints
    allowed={f.name for f in fields(DetailedPenaltyInputs)}
    extras=set(payload)-allowed
    if extras: raise HTTPException(422,'Unexpected penalty fields: '+', '.join(sorted(extras)))
    monetary={'balance','annual_rate','comparison_posted_rate','original_posted_rate',
      'documented_discount','monthly_payment','payout_amount','privilege_available',
      'cashback_clawback','discharge_fee','administration_fee','reinvestment_fee','other_fee'}
    try:
        parsed={k:Decimal(str(v)) if k in monetary and v is not None else v for k,v in payload.items()}
        if parsed.get('explicit_method') is not None:
            parsed['explicit_method']=Method(parsed['explicit_method'])
        result=detailed_penalty(DetailedPenaltyInputs(**parsed))
        return result.as_dict()
    except (TypeError,ValueError,ArithmeticError) as exc:
        raise HTTPException(422,str(exc))

# Phase IV: provenance-backed historical rates and tenant-isolated broker tools.
# Neither service pulls third-party bank account data without consent.
from .intelligence.rate_history import RateArchive, RateObservation
from .broker.workspace import BrokerWorkspace, AccessDenied
from pydantic import BaseModel, Field

(ROOT / 'data').mkdir(parents=True, exist_ok=True)
rates_archive = RateArchive(ROOT / 'data' / 'rate-history.sqlite3')
broker_workspace = BrokerWorkspace(ROOT / 'data' / 'broker-workspaces.sqlite3')

from .broker.dashboard import BrokerDashboard
from .leads.engine import LeadEngine
from .leads.identity import Vault
from .rates.service import reference_book
from .rates.models import CHARTERED
from .routers.v5 import build_router, _sandbox_service
from .services import store as case_store

def _frontend_check():
    index = FRONTEND / 'index.html'
    if not index.is_file():
        raise FileNotFoundError('frontend assets missing')
    return 'ok'

def _case_store_check():
    case_store.initialize()
    return 'ok'

def _market_rate(lender, day):
    hit = reference_book().posted_at(lender or CHARTERED, 60, day)
    return None if hit is None else hit.rate

broker_dashboard = BrokerDashboard(broker_workspace, market_rate=_market_rate)
banklink_service = _sandbox_service()
from .banklink.gateway import BankLinkGateway
banklink_gateway = BankLinkGateway(banklink_service)
_lead_engine = None
LEADS_DB = ROOT / 'data' / 'leads.sqlite3'

def get_lead_engine():
    global _lead_engine
    from renewal import main as main_mod
    if main_mod._lead_engine is not None:
        return main_mod._lead_engine
    key = os.environ.get('RR_LEAD_KEY', '')
    secret = os.environ.get('RR_LEAD_DEDUPE_SECRET', '')
    if not key or len(secret) < 32:
        raise HTTPException(503, 'Lead engine not configured')
    engine = LeadEngine(
        main_mod.LEADS_DB,
        Vault(key.encode() if isinstance(key, str) else key),
        secret.encode() if isinstance(secret, str) else secret,
    )
    main_mod._lead_engine = engine
    return engine

app.include_router(build_router(
    broker_workspace=broker_workspace,
    broker_dashboard=broker_dashboard,
    banklink_service=banklink_service,
    banklink_gateway=banklink_gateway,
    get_lead_engine=get_lead_engine,
    frontend_check=_frontend_check,
    case_store_check=_case_store_check,
    connectors=lambda: {
        'model': bool(settings.nebius_api_key),
        'search': bool(settings.tavily_api_key),
    },
))

class RateSubmission(BaseModel):
    lender: str
    product: str
    rate_type: str
    term_months: int
    annual_rate: str
    rate_kind: str
    effective_at: str
    captured_at: str
    source_url: str
    source_sha256: str
    evidence: str
    provenance: str = 'official_lender_page'

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

class BrokerClientCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=120)
    renewal_date: str | None = None

class BrokerConsentCreate(BaseModel):
    scope: str
    status: str
    evidence: str = Field(min_length=1, max_length=500)

@app.post('/api/v4/rates/observations', status_code=201)
async def add_rate_observation(body: RateSubmission, x_rate_ingest_key: str | None = Header(None)):
    """Restricted ingestion endpoint; not exposed with a default credential."""
    import secrets
    key = os.environ.get('RR_RATE_INGEST_KEY', '')
    if len(key) < 24 or not secrets.compare_digest(x_rate_ingest_key or '', key):
        raise HTTPException(403, 'Rate ingestion unavailable without configured ingest key')
    try:
        return rates_archive.append(RateObservation(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v4/rates/history')
async def rate_history(lender: str = Query(min_length=1,max_length=100),
                       term_months: int | None = None,
                       rate_type: str | None = None, rate_kind: str | None = None,
                       as_of: str | None = None, limit: int = Query(100,ge=1,le=500)):
    try:
        return {'observations': rates_archive.history(lender, term_months=term_months,
            rate_type=rate_type, rate_kind=rate_kind, as_of=as_of, limit=limit),
            'notice': 'Historical public observations, not guaranteed available borrower rates.'}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v4/rates/historical-discount')
async def rate_historical_discount(lender: str, origination_at: str,
                                   contract_rate: str, term_months: int):
    try:
        return rates_archive.reconstruct_discount(lender, origination_at,
                                                   contract_rate, term_months)
    except (ValueError,ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v4/broker/workspaces', status_code=201)
async def create_broker_workspace(body: WorkspaceCreate):
    # Demo-only: restrict registration in production by identity provider.
    # Temporary until OIDC/workspace SSO: demo workspaces only when explicitly enabled
    # and never in production (see security.access.demo_enabled).
    if not demo_enabled():
        raise HTTPException(403, 'Demo workspace creation is disabled')
    return broker_workspace.create_workspace(body.name)

def broker_auth(wid: str, token: str | None):
    try:
        broker_workspace._assert_access(wid, token or '')
    except AccessDenied:
        raise HTTPException(404, 'Workspace not found')

@app.post('/api/v4/broker/workspaces/{wid}/clients', status_code=201)
async def broker_add_client(wid: str, body: BrokerClientCreate,
                            x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    try:
        return broker_workspace.add_client(wid, x_broker_token or '',
                                           body.alias, body.renewal_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v4/broker/workspaces/{wid}/clients')
async def broker_list_clients(wid: str, x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return {'clients': broker_workspace.clients(wid, x_broker_token or '')}

@app.post('/api/v4/broker/workspaces/{wid}/clients/{cid}/consents', status_code=201)
async def broker_record_consent(wid: str, cid: str, body: BrokerConsentCreate,
                                x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    try:
        return broker_workspace.record_consent(wid, x_broker_token or '', cid,
                                               body.scope, body.status, body.evidence)
    except AccessDenied:
        raise HTTPException(404, 'Client not found')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v4/broker/workspaces/{wid}/clients/{cid}/consents/{scope}')
async def broker_check_consent(wid: str, cid: str, scope: str,
                               x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return {'scope': scope, 'granted': broker_workspace.has_consent(wid, x_broker_token or '', cid, scope)}

@app.get('/api/v4/broker/workspaces/{wid}/audit')
async def broker_audit(wid: str, x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return {'events': broker_workspace.audit(wid, x_broker_token or '')}

# V5 source-collection audit endpoint: read only. Scheduled fetches are a CLI
# operation, not a public HTTP route, preventing an unauthenticated SSRF trigger.
from .intelligence.collector import CollectionJournal
rate_collection_journal = CollectionJournal(ROOT / 'data' / 'rate-collection.sqlite3')

@app.get('/api/v5/rates/collection/status')
async def rate_collection_status():
    events = rate_collection_journal.recent(limit=20)
    return {
        'recent': events,
        'total_in_response': len(events),
        'notice': 'Automated official-page collection is source restricted. Missing or ambiguous values are quarantined; historic dates are not inferred.'
    }

# V6: milestone-based broker renewal queue. No automatic outreach is performed.
from .broker.renewal_queue import RenewalQueue
renewal_queue = RenewalQueue(ROOT / 'data' / 'renewal-queue.sqlite3')

class RenewalTaskUpdate(BaseModel):
    state: str
    note: str = Field(default='', max_length=1000)

@app.post('/api/v6/broker/workspaces/{wid}/renewal-tasks/synchronize')
async def broker_sync_renewal_tasks(wid: str,
                                    x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    token = x_broker_token or ''
    clients = broker_workspace.clients(wid, token)
    records = []
    for client in clients:
        if client.get('renewal_date'):
            consent = broker_workspace.has_consent(
                wid, token, client['id'], 'contact_homeowner')
            records.append({'client_id': client['id'],
                            'renewal_date': client['renewal_date'],
                            'contact_consent': consent})
    return renewal_queue.synchronize(wid, records)

@app.get('/api/v6/broker/workspaces/{wid}/renewal-tasks')
async def broker_get_renewal_tasks(wid: str,
                                  state: str = 'open',
                                  limit: int = Query(default=100, ge=1, le=1000),
                                  x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    try:
        tasks = renewal_queue.list_tasks(wid, state=state, limit=limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for task in tasks:
        task['contact_consent_current'] = broker_workspace.has_consent(
            wid, x_broker_token or '', task['client_id'], 'contact_homeowner')
    return {'tasks': tasks, 'notifications_sent': 0,
            'notice': 'Tasks are planning prompts; contact requires independently verified current consent.'}

@app.put('/api/v6/broker/workspaces/{wid}/renewal-tasks/{task_id}')
async def broker_update_renewal_task(wid: str, task_id: str, body: RenewalTaskUpdate,
                                     x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    try:
        updated = renewal_queue.change_state(wid, task_id, body.state, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if updated is None:
        raise HTTPException(404, 'Renewal task not found')
    return updated

@app.get('/api/v6/broker/workspaces/{wid}/renewal-tasks/{task_id}/audit')
async def broker_renewal_task_audit(wid: str, task_id: str,
                                    x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return {'events': renewal_queue.events(wid, task_id)}

# V7: Evidence-based lender penalty reference comparison.
# Never expose uploaded borrower payout statements through this public endpoint.
# Only structured redacted reference cases are accepted; synthetic fixtures are
# excluded from accuracy statistics and an exactness claim is never inferred.
from .penalty.verification import ReferenceCase, ReferenceError, verify_cases

@app.post('/api/penalty/v7/verify')
async def penalty_v7_verify(payload: dict[str, Any]):
    from .penalty.verification import MAX_CASES
    raw = payload.get('cases')
    if not isinstance(raw, list) or len(raw) > MAX_CASES:
        raise HTTPException(422, f'cases must be an array of at most {MAX_CASES} items')
    try:
        return verify_cases(ReferenceCase.from_dict(item) for item in raw)
    except (ReferenceError, ValueError, ArithmeticError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc

# V9: consent-gated banking connectivity foundation.
# This sandbox/local connector creates auditable authorization sessions,
# token-vault records and imported snapshots without contacting a bank.
from .banking.open_banking import (
    OpenBankingConnector, BankingError, BankingAccessDenied,
    BankingSessionExpired, ConsentRequired,
)

open_banking = OpenBankingConnector(ROOT / 'data' / 'open-banking.sqlite3')

class BankingSessionCreate(BaseModel):
    institution_id: str = Field(min_length=1, max_length=120)
    redirect_uri: str = Field(min_length=8, max_length=500)
    scopes: list[str] = Field(default_factory=lambda: [
        'accounts.basic', 'accounts.balance', 'transactions.read'
    ], max_length=8)
    expires_minutes: int = Field(default=15, ge=1, le=60)

class BankingExchange(BaseModel):
    authorization_code: str = Field(min_length=1, max_length=300)
    state: str = Field(min_length=20, max_length=2000)

class BankingSnapshotImport(BaseModel):
    accounts: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    transactions: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    refreshed_at: str | None = None

def raise_banking_http(exc: Exception):
    if isinstance(exc, BankingAccessDenied):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ConsentRequired):
        raise HTTPException(403, str(exc)) from exc
    if isinstance(exc, BankingSessionExpired):
        raise HTTPException(410, str(exc)) from exc
    if isinstance(exc, BankingError):
        raise HTTPException(422, str(exc)) from exc
    raise exc

@app.get('/api/v9/banking/institutions')
async def banking_institutions():
    return {'institutions': open_banking.institutions(),
      'notice': 'Sandbox institutions only; production requires a reviewed provider contract.'}

@app.post('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/sessions', status_code=201)
async def banking_create_session(wid: str, cid: str, body: BankingSessionCreate,
                                 x_broker_token: str | None = Header(None)):
    try:
        return open_banking.create_session(workspace_id=wid, broker_token=x_broker_token or '',
          client_id=cid, institution_id=body.institution_id, redirect_uri=body.redirect_uri,
          scopes=body.scopes, broker_workspace=broker_workspace,
          expires_minutes=body.expires_minutes)
    except Exception as exc:
        raise_banking_http(exc)

@app.post('/api/v9/broker/workspaces/{wid}/banking/sessions/{session_id}/exchange')
async def banking_exchange_session(wid: str, session_id: str, body: BankingExchange,
                                   x_broker_token: str | None = Header(None)):
    try:
        return open_banking.exchange_session(workspace_id=wid, broker_token=x_broker_token or '',
          session_id=session_id, authorization_code=body.authorization_code,
          state=body.state, broker_workspace=broker_workspace)
    except Exception as exc:
        raise_banking_http(exc)

@app.get('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections')
async def banking_list_connections(wid: str, cid: str,
                                   x_broker_token: str | None = Header(None)):
    try:
        return {'connections': open_banking.list_connections(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid,
          broker_workspace=broker_workspace)}
    except Exception as exc:
        raise_banking_http(exc)

@app.delete('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}')
async def banking_revoke_connection(wid: str, cid: str, connection_id: str,
                                    x_broker_token: str | None = Header(None)):
    try:
        return open_banking.revoke_connection(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid,
          connection_id=connection_id, broker_workspace=broker_workspace)
    except Exception as exc:
        raise_banking_http(exc)

@app.post('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/connections/{connection_id}/snapshot')
async def banking_import_snapshot(wid: str, cid: str, connection_id: str,
                                  body: BankingSnapshotImport,
                                  x_broker_token: str | None = Header(None)):
    try:
        return open_banking.import_snapshot(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid, connection_id=connection_id,
          accounts=body.accounts, transactions=body.transactions,
          broker_workspace=broker_workspace, refreshed_at=body.refreshed_at)
    except Exception as exc:
        raise_banking_http(exc)

@app.get('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/accounts')
async def banking_accounts(wid: str, cid: str,
                           x_broker_token: str | None = Header(None)):
    try:
        return {'accounts': open_banking.accounts(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid,
          broker_workspace=broker_workspace)}
    except Exception as exc:
        raise_banking_http(exc)

@app.get('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/payment-evidence')
async def banking_payment_evidence(wid: str, cid: str,
                                   months: int = Query(default=18, ge=1, le=36),
                                   lender_hint: str | None = Query(default=None, max_length=120),
                                   x_broker_token: str | None = Header(None)):
    try:
        return open_banking.payment_evidence(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid,
          broker_workspace=broker_workspace, months=months, lender_hint=lender_hint)
    except Exception as exc:
        raise_banking_http(exc)

@app.get('/api/v9/broker/workspaces/{wid}/clients/{cid}/banking/cashflow')
async def banking_cashflow(wid: str, cid: str,
                           months: int = Query(default=6, ge=1, le=36),
                           x_broker_token: str | None = Header(None)):
    try:
        return open_banking.cashflow_summary(workspace_id=wid,
          broker_token=x_broker_token or '', client_id=cid,
          broker_workspace=broker_workspace, months=months)
    except Exception as exc:
        raise_banking_http(exc)

@app.get('/api/v9/broker/workspaces/{wid}/banking/events')
async def banking_events(wid: str,
                         client_id: str | None = Query(default=None, max_length=120),
                         limit: int = Query(default=100, ge=1, le=500),
                         x_broker_token: str | None = Header(None)):
    try:
        return {'events': open_banking.events(workspace_id=wid,
          broker_token=x_broker_token or '', broker_workspace=broker_workspace,
          client_id=client_id, limit=limit)}
    except Exception as exc:
        raise_banking_http(exc)

# V8 camera pipeline: never persist raw image or recognized personal data.
from .ocr.camera import prepare_scan, CameraSettings, CameraError, scans_to_pdf, decide_recapture
from .ocr.engines import choose_engine, OCREngineError

@app.post('/api/v8/camera/inspect')
async def camera_inspect(file: UploadFile = File(...)):
    if file.content_type not in ('image/jpeg', 'image/png', 'image/webp', 'image/tiff',
                                 'application/octet-stream'):
        raise HTTPException(415, 'Unsupported image MIME type.')
    payload = await read_upload_capped(file, max_bytes=MAX_UPLOAD_BYTES)
    await file.close()
    try:
        scan = prepare_scan(payload)
        return {'scan': scan.metadata(),
                'recapture': decide_recapture(scan.quality),
                'document_saved': False,
                'notice': 'Quality scores are heuristics; confirm all financial fields manually.'}
    except CameraError as exc:
        raise HTTPException(422, str(exc)) from exc

# V10 OCR field-review workflow. This accepts OCR text, not raw image bytes,
# and returns bounded field evidence plus manual-review prompts.
from .ocr.fields import OCRFieldError, extract_ocr_fields, summarize_review_decision
from .ocr.document_understanding import understand_ocr_document
from .ocr.engine_registry import (
    OCREngineRegistryError, list_engine_profiles, recommend_ocr_engines,
)
from .ocr.mortgage_terms import glossary_public
from .ocr.review_sessions import (
    OCRReviewAccessDenied, OCRReviewConflict, OCRReviewSessionError,
    OCRReviewSessionStore,
)
from .ocr.contract_intelligence import (
    ContractIntelligenceError, create_contract_brief,
)
from .ocr.contract_math_v13 import ContractMathAuditError, create_contract_math_audit
from .ocr.contract_packet_v13 import ContractPacketError, create_lender_packet
from .ocr.contract_playbook import ContractPlaybookError, create_contract_playbook
from .ocr.contract_sources import contract_source_map
from .ocr.adapter_output_normalizer_v15 import (
    AdapterNormalizationError, normalize_adapter_payload, preview_adapter_payload,
)
from .ocr.adapter_quality_harness_v15 import (
    AdapterQualityHarnessError, evaluate_adapter_payload,
)
from .ocr.adapter_reconciliation_v15 import (
    AdapterReconciliationError, build_reconciliation_report,
)
from .ocr.adapter_workbench_v15 import AdapterWorkbenchError, build_workbench_report
from .ocr.adapter_benchmark_suite_v15 import (
    AdapterBenchmarkError, run_adapter_benchmark_suite,
)
from .ocr.document_semantic_auditor_v16 import create_document_semantic_audit
from .ocr.semantic_evidence_v16 import DocumentSemanticAuditError
from .ocr.semantic_pdf_v16 import audit_semantic_pdf
from .ocr.dependency_adapters_v14 import (
    DependencyAdapterError, create_dependency_adapter_plan,
    create_adapter_readiness_report, optional_dependency_registry,
    optional_requirements_lines,
)
from .ocr.research_radar_v13 import (
    ResearchRadarError, create_research_radar, research_source_map,
)

ocr_review_sessions = OCRReviewSessionStore(ROOT / 'data' / 'ocr-review-sessions.sqlite3')

class OCRTextPageInput(BaseModel):
    page_number: int | None = Field(default=None, ge=1, le=200)
    text: str = Field(min_length=0, max_length=25000)
    mean_confidence: float | None = Field(default=None, ge=0, le=1)

class OCRFieldsRequest(BaseModel):
    pages: list[OCRTextPageInput] = Field(min_length=1, max_length=16)
    filename: str = Field(default='ocr.txt', max_length=120)
    min_confidence: float = Field(default=0.0, ge=0, le=1)

class OCRReviewRequest(OCRFieldsRequest):
    corrections: dict[str, Any] = Field(default_factory=dict, max_length=20)

class OCREnginePlanRequest(BaseModel):
    document_type: str = Field(default='unknown', max_length=40)
    privacy_mode: str = Field(default='local_only', max_length=40)
    setup_budget: str = Field(default='low', max_length=40)
    output_goal: str = Field(default='fields', max_length=40)
    needs_layout: bool = False
    needs_tables: bool = False
    photographed_document: bool = False
    allow_gpu: bool = False
    languages: list[str] = Field(default_factory=lambda: ['eng'], max_length=12)

class OCRReviewSessionCreate(OCRReviewRequest):
    borrower_alias: str | None = Field(default=None, max_length=120)
    source: str = Field(default='uploaded_ocr_text', max_length=80)
    actor: str = Field(default='system', max_length=120)
    expires_days: int = Field(default=45, ge=1, le=180)

class OCRSessionCorrectionRequest(BaseModel):
    corrections: dict[str, Any] = Field(default_factory=dict, max_length=20)
    actor: str = Field(default='reviewer', max_length=120)
    note: str = Field(default='', max_length=1000)

class OCRFieldDecisionInput(BaseModel):
    field: str = Field(min_length=1, max_length=80)
    decision: str = Field(min_length=1, max_length=40)
    reason: str = Field(default='', max_length=1000)

class OCRSessionDecisionRequest(BaseModel):
    decisions: list[OCRFieldDecisionInput] = Field(min_length=1, max_length=30)
    actor: str = Field(default='reviewer', max_length=120)
    note: str = Field(default='', max_length=1000)

class OCRSessionFinalizeRequest(BaseModel):
    actor: str = Field(default='reviewer', max_length=120)
    note: str = Field(default='', max_length=1000)

class ContractBriefRequest(OCRReviewRequest):
    question: str | None = Field(default=None, max_length=500)

class DocumentSemanticAuditRequest(OCRReviewRequest):
    as_of: date | None = None

class AdapterPayloadRequest(BaseModel):
    adapter: str | None = Field(default=None, max_length=80)
    payload: Any

class AdapterWorkbenchRequest(BaseModel):
    candidates: list[AdapterPayloadRequest] = Field(min_length=1, max_length=8)

class AdapterBenchmarkRequest(BaseModel):
    adapters: list[str] | None = Field(default=None, max_length=12)
    include_candidate_sets: bool = True

def _ocr_session_token(value: str | None) -> str:
    if not value:
        raise HTTPException(403, 'Missing OCR review session token')
    return value

def _raise_ocr_session(exc: Exception):
    if isinstance(exc, OCRReviewAccessDenied):
        raise HTTPException(403, str(exc)) from exc
    if isinstance(exc, OCRReviewConflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, (OCRReviewSessionError, OCRFieldError, OCREngineRegistryError,
                        ContractIntelligenceError, ContractPlaybookError,
                        AdapterNormalizationError, AdapterQualityHarnessError,
                        AdapterReconciliationError, AdapterWorkbenchError,
                        AdapterBenchmarkError, DocumentSemanticAuditError,
                        ContractMathAuditError, ContractPacketError,
                        DependencyAdapterError, ResearchRadarError)):
        raise HTTPException(422, str(exc)) from exc
    raise exc

@app.post('/api/v10/ocr/fields')
async def ocr_fields(body: OCRFieldsRequest):
    try:
        return extract_ocr_fields([page.model_dump() for page in body.pages],
            filename=body.filename, min_confidence=body.min_confidence)
    except OCRFieldError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v10/ocr/review')
async def ocr_review(body: OCRReviewRequest):
    try:
        extraction = extract_ocr_fields([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence)
        return {**extraction, 'review_summary': summarize_review_decision(extraction)}
    except OCRFieldError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v11/ocr/engines')
async def ocr_engines():
    return list_engine_profiles()

@app.post('/api/v11/ocr/engine-plan')
async def ocr_engine_plan(body: OCREnginePlanRequest):
    try:
        return recommend_ocr_engines(body.model_dump())
    except OCREngineRegistryError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v11/mortgage/terms')
async def mortgage_terms():
    return glossary_public()

@app.post('/api/v11/ocr/understand')
async def ocr_understand(body: OCRReviewRequest):
    try:
        return understand_ocr_document([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence)
    except (OCRFieldError, OCRReviewSessionError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v12/contract-intelligence/sources')
async def contract_intelligence_sources():
    return contract_source_map()

@app.post('/api/v12/contract-intelligence/brief')
async def contract_intelligence_brief(body: ContractBriefRequest):
    try:
        return create_contract_brief([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v12/contract-intelligence/answer')
async def contract_intelligence_answer(body: ContractBriefRequest):
    if not body.question:
        raise HTTPException(422, 'Question is required')
    try:
        brief = create_contract_brief([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
        return {'answer': brief['answer'], 'evidence_graph': brief['evidence_graph'],
                'risk_assessment': brief['risk_assessment'],
                'readiness': brief['readiness']}
    except (OCRFieldError, ContractIntelligenceError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v12/contract-intelligence/playbook')
async def contract_intelligence_playbook(body: ContractBriefRequest):
    try:
        return create_contract_playbook([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractPlaybookError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v13/contract-intelligence/research-sources')
async def contract_research_sources():
    return research_source_map()

@app.post('/api/v13/contract-intelligence/math-audit')
async def contract_math_audit(body: ContractBriefRequest):
    try:
        return create_contract_math_audit([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractMathAuditError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v13/contract-intelligence/research-radar')
async def contract_research_radar(body: ContractBriefRequest):
    try:
        return create_research_radar([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v13/contract-intelligence/lender-packet')
async def contract_lender_packet(body: ContractBriefRequest):
    try:
        return create_lender_packet([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ContractPacketError, ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/api/v14/ocr/optional-dependencies')
async def ocr_optional_dependencies():
    registry = optional_dependency_registry()
    return {
        'provider': 'optional-ocr-dependencies-v14',
        'dependency_count': len(registry),
        'dependencies': [registry[key].public() for key in sorted(registry)],
        'optional_requirements': optional_requirements_lines(registry),
        'notice': 'These packages are built in as optional adapter profiles, not required runtime dependencies.',
    }

@app.post('/api/v14/contract-intelligence/dependency-plan')
async def contract_dependency_plan(body: ContractBriefRequest):
    try:
        return create_dependency_adapter_plan([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ContractPacketError, DependencyAdapterError,
            ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v14/contract-intelligence/adapter-readiness')
async def contract_adapter_readiness(body: ContractBriefRequest):
    try:
        return create_adapter_readiness_report([page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, question=body.question)
    except (OCRFieldError, ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ContractPacketError, DependencyAdapterError,
            ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-normalize')
async def ocr_adapter_normalize(body: AdapterPayloadRequest):
    try:
        return normalize_adapter_payload(body.payload, body.adapter)
    except AdapterNormalizationError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-preview')
async def ocr_adapter_preview(body: AdapterPayloadRequest):
    try:
        return preview_adapter_payload(body.payload, body.adapter)
    except AdapterNormalizationError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-evaluate')
async def ocr_adapter_evaluate(body: AdapterPayloadRequest):
    try:
        return evaluate_adapter_payload(body.payload, body.adapter)
    except (AdapterNormalizationError, AdapterQualityHarnessError,
            OCRFieldError, ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ContractPacketError, DependencyAdapterError,
            ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-workbench')
async def ocr_adapter_workbench(body: AdapterWorkbenchRequest):
    try:
        return build_workbench_report([
            {'adapter': item.adapter, 'payload': item.payload}
            for item in body.candidates
        ])
    except (AdapterNormalizationError, AdapterQualityHarnessError,
            AdapterWorkbenchError, OCRFieldError, ContractIntelligenceError,
            ContractMathAuditError, ContractPlaybookError, ContractPacketError,
            DependencyAdapterError, ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-reconcile')
async def ocr_adapter_reconcile(body: AdapterWorkbenchRequest):
    try:
        return build_reconciliation_report([
            {'adapter': item.adapter, 'payload': item.payload}
            for item in body.candidates
        ])
    except (AdapterNormalizationError, AdapterQualityHarnessError,
            AdapterReconciliationError, AdapterWorkbenchError, OCRFieldError,
            ContractIntelligenceError, ContractMathAuditError,
            ContractPlaybookError, ContractPacketError, DependencyAdapterError,
            ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v15/ocr/adapter-benchmark')
async def ocr_adapter_benchmark(body: AdapterBenchmarkRequest):
    try:
        return run_adapter_benchmark_suite(
            body.adapters,
            include_candidate_sets=body.include_candidate_sets,
        )
    except (AdapterNormalizationError, AdapterQualityHarnessError,
            AdapterReconciliationError, AdapterWorkbenchError,
            AdapterBenchmarkError, OCRFieldError, ContractIntelligenceError,
            ContractMathAuditError, ContractPlaybookError, ContractPacketError,
            DependencyAdapterError, ResearchRadarError) as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v16/ocr/semantic-audit')
async def document_semantic_audit(body: DocumentSemanticAuditRequest):
    try:
        return create_document_semantic_audit(
            [page.model_dump() for page in body.pages],
            filename=body.filename, corrections=body.corrections,
            min_confidence=body.min_confidence, as_of=body.as_of,
        )
    except DocumentSemanticAuditError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/v16/ocr/semantic-audit/pdf')
async def document_semantic_pdf(file: UploadFile = File(...)):
    try:
        ingested = await ingest_document_upload(file, allowed={'pdf'})
        return audit_semantic_pdf(ingested.data, ingested.filename)
    except DocumentSemanticAuditError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()

@app.post('/api/v11/ocr/review-sessions', status_code=201)
async def ocr_review_session_create(body: OCRReviewSessionCreate):
    try:
        return ocr_review_sessions.create_session(
            [page.model_dump() for page in body.pages],
            filename=body.filename,
            min_confidence=body.min_confidence,
            corrections=body.corrections,
            borrower_alias=body.borrower_alias,
            source=body.source,
            actor=body.actor,
            expires_days=body.expires_days,
        )
    except Exception as exc:
        _raise_ocr_session(exc)

@app.get('/api/v11/ocr/review-sessions/{session_id}')
async def ocr_review_session_get(session_id: str,
                                 x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.get_session(
            session_id, _ocr_session_token(x_ocr_review_token))
    except Exception as exc:
        _raise_ocr_session(exc)

@app.post('/api/v11/ocr/review-sessions/{session_id}/corrections')
async def ocr_review_session_corrections(session_id: str, body: OCRSessionCorrectionRequest,
                                         x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.apply_corrections(
            session_id, _ocr_session_token(x_ocr_review_token), body.corrections,
            actor=body.actor, note=body.note)
    except Exception as exc:
        _raise_ocr_session(exc)

@app.post('/api/v11/ocr/review-sessions/{session_id}/decisions')
async def ocr_review_session_decisions(session_id: str, body: OCRSessionDecisionRequest,
                                       x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.record_decisions(
            session_id, _ocr_session_token(x_ocr_review_token),
            [item.model_dump() for item in body.decisions],
            actor=body.actor, note=body.note)
    except Exception as exc:
        _raise_ocr_session(exc)

@app.post('/api/v11/ocr/review-sessions/{session_id}/finalize')
async def ocr_review_session_finalize(session_id: str, body: OCRSessionFinalizeRequest,
                                      x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.finalize_session(
            session_id, _ocr_session_token(x_ocr_review_token),
            actor=body.actor, note=body.note)
    except Exception as exc:
        _raise_ocr_session(exc)

@app.get('/api/v11/ocr/review-sessions/{session_id}/audit')
async def ocr_review_session_audit(session_id: str,
                                   x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.audit_events(
            session_id, _ocr_session_token(x_ocr_review_token))
    except Exception as exc:
        _raise_ocr_session(exc)

@app.get('/api/v11/ocr/review-sessions/{session_id}/export')
async def ocr_review_session_export(session_id: str,
                                    x_ocr_review_token: str | None = Header(None)):
    try:
        return ocr_review_sessions.export_packet(
            session_id, _ocr_session_token(x_ocr_review_token))
    except Exception as exc:
        _raise_ocr_session(exc)

@app.post('/api/v8/camera/ocr')
async def camera_ocr(file: UploadFile = File(...),
                     engine: str = Query(default='tesseract', pattern='^(auto|tesseract|docling|paddleocr|easyocr|rapidocr)$'),
                     language: str = Query(default='eng', max_length=8)):
    if file.content_type not in ('image/jpeg', 'image/png', 'image/webp', 'image/tiff',
                                 'application/octet-stream'):
        raise HTTPException(415, 'Unsupported image MIME type.')
    payload = await read_upload_capped(file, max_bytes=MAX_UPLOAD_BYTES)
    await file.close()
    try:
        scan = prepare_scan(payload)
        result = choose_engine(engine, language=language).recognize(scan)
        return {'ocr': result.summary(include_words=True),
                'scan': scan.metadata(),
                'recapture': decide_recapture(scan.quality),
                'requires_manual_field_verification': True,
                'notice': 'No automated OCR reading is proof of a mortgage rate, balance or maturity date.'}
    except CameraError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OCREngineError as exc:
        raise HTTPException(503, str(exc)) from exc

@app.post('/api/v8/camera/pdf')
async def camera_pdf(files: list[UploadFile] = File(...)):
    if not 1 <= len(files) <= 12:
        raise HTTPException(422, 'Supply between 1 and 12 document photographs.')
    prepared = []
    try:
        for file in files:
            if file.content_type not in ('image/jpeg', 'image/png', 'image/webp', 'image/tiff',
                                         'application/octet-stream'):
                raise HTTPException(415, 'Unsupported image MIME type.')
            prepared.append(prepare_scan(await read_upload_capped(file, max_bytes=MAX_UPLOAD_BYTES)))
            await file.close()
        pdf_bytes = scans_to_pdf(prepared)
        return Response(pdf_bytes, media_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="camera-document.pdf"',
                                 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except CameraError as exc:
        raise HTTPException(422, str(exc)) from exc
