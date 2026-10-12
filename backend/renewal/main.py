"""Renewal Radar HTTP API and built-in commercial-style web UI.

Run: PYTHONPATH=backend uvicorn renewal.main:app --reload
Open: http://127.0.0.1:8000
"""
from __future__ import annotations
import os,sys,json,logging
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException,UploadFile,File,Body,Header,Query
from fastapi.responses import JSONResponse,Response,FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from .config import settings
from .domain.schemas import AnalyzeRequest,Mortgage,Offer,PenaltyRequest,CaseCreate,ShareRequest,NegotiationRequest
from .domain.mortgage_math import compare_offers,stress_paths,simulate
from .domain.rules import mqr,switch_decision,penalty_estimate,OSFI_MQR,OSFI_SWITCH,RENEWAL
from .services.extract import extract_pdf
from .services.market import fetch_boc,bank_catalog
from .services.agent import explain,enrich_extraction,TOOLS
from .services.negotiation import negotiation_packet
from .services.plan import make_plan,create_ics
from .services.report import render_report
from .services.ledger import ledger_csv,annual_summary
from .services import store
from .providers.bank_rates import fetch_bank_posted_rates
from .providers.tavily import discover
from .security.rate_limit import SlidingWindowLimiter
from .observability.health import readiness

ROOT=Path(__file__).resolve().parents[2]
FRONTEND=ROOT/'frontend'
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger('renewal_radar')

@asynccontextmanager
async def lifespan(app:FastAPI):
    store.initialize()
    yield

app=FastAPI(title='Renewal Radar 2.0',version='2.0.0',
    description='Canadian mortgage renewal analysis, source-backed rule engine, privacy-conscious agent and PDF reports',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=list(settings.allowed_origins),allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-Case-Token'])

limiter=SlidingWindowLimiter()

def _security_headers(response,path:str):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']=(
       "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
    if path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.middleware('http')
async def security_and_rate_limit(request,call_next):
    decision=None
    if settings.rate_limit_enabled:
        client=request.client.host if request.client else 'unknown'
        decision=limiter.check(client,request.url.path)
        if decision is not None and not decision.allowed:
            retry=max(1,int(decision.retry_after+0.999))
            response=JSONResponse({'detail':'Too many requests; please retry shortly.'},status_code=429,
                                  headers={'Retry-After':str(retry),'X-RateLimit-Limit':str(decision.limit),
                                           'X-RateLimit-Remaining':'0'})
            return _security_headers(response,request.url.path)
    response=await call_next(request)
    if decision is not None:
        response.headers['X-RateLimit-Limit']=str(decision.limit)
        response.headers['X-RateLimit-Remaining']=str(decision.remaining)
    return _security_headers(response,request.url.path)

@app.get('/api/health')
async def health():
    return {'status':'ok','product':'Renewal Radar','version':'2.0.0',
            'ai_configured':bool(settings.nebius_api_key),'tavily_configured':bool(settings.tavily_api_key),
            'timestamp':datetime.now(timezone.utc).isoformat()}

@app.get('/api/health/live')
async def health_live():
    return {'status':'alive'}

def _store_check():
    with store.engine.connect() as conn:
        conn.exec_driver_sql('SELECT 1')
    return 'case store reachable'

def _frontend_check():
    if not (FRONTEND/'index.html').is_file():
        raise FileNotFoundError('frontend/index.html')
    return 'frontend assets present'

@app.get('/api/health/ready')
async def health_ready():
    report=readiness([('case_store',_store_check),('frontend',_frontend_check)],
                     connectors={'model':bool(settings.nebius_api_key),'search':bool(settings.tavily_api_key)})
    return JSONResponse(report,status_code=200 if report['status']=='ready' else 503)

@app.get('/api/demo')
async def demo():
    return {'mortgage':Mortgage().model_dump(),
       'offers':[Offer(name='Illustrative alternative',rate=4.49,rate_type='fixed',term_months=36,type='hypothetical',fees=950).model_dump(),
                 Offer(name='Illustrative variable',rate=4.25,rate_type='variable',term_months=36,type='hypothetical',fees=1100).model_dump()],
       'case_title':'Sample renewal: $480,000 balance',
       'notice':'Entire demonstration uses fictional lender and illustrative alternatives, not quotes or verified mortgage commitments.'}

@app.get('/api/demo/sample.pdf')
async def demo_pdf():
    return FileResponse(ROOT/'fixtures'/'fictional-renewal-letter.pdf',media_type='application/pdf',headers={'Cache-Control':'no-store'})

@app.post('/api/documents/extract')
async def pdf_extract(file: UploadFile=File(...)):
    if file.content_type not in ('application/pdf','application/octet-stream') and not file.filename.lower().endswith('.pdf'):
        raise HTTPException(415,'Only PDF documents are accepted.')
    content=await file.read(settings.max_pdf_bytes+1)
    await file.close()
    if len(content)>settings.max_pdf_bytes:
        raise HTTPException(413,f'PDF must be smaller than {settings.max_pdf_bytes//1048576} MB.')
    try:
        extracted=extract_pdf(content,file.filename)
        extracted=await enrich_extraction(extracted)
        return extracted.model_dump()
    except ValueError as exc:raise HTTPException(422,str(exc))

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
async def cases_create(body:CaseCreate):
    return store.create_case(body.title,{'mortgage':body.mortgage.model_dump(),'offers':[o.model_dump() for o in body.offers]})

def access_or_404(uid,token):
    obj=store.read_case(uid,token)
    if not obj:raise HTTPException(404,'Case not found or access token invalid')
    return obj

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

@app.get('/shared/{token}')
async def shared_page(token:str):return FileResponse(FRONTEND/'index.html')

app.mount('/assets',StaticFiles(directory=FRONTEND/'assets'),name='assets')
app.mount('/js',StaticFiles(directory=FRONTEND/'js'),name='js')

# Transparent lender-profiled penalty API. Kept separate from the legacy
# approximation endpoint for backward compatibility with existing clients.
from .penalty import PenaltyInputs as DetailedPenaltyInputs, calculate_penalty as detailed_penalty
from .penalty.profiles import lender_profiles as detailed_lender_profiles
from decimal import Decimal
from datetime import date
from typing import Any
from pydantic import BaseModel, Field
from .penalty.comparison import TermRule
from .penalty.methods import all_specs as all_method_specs
from .penalty.workbench import WorkbenchCase, run_workbench

@app.get('/api/penalty/v3/lenders')
async def penalty_v3_lenders():
    return {'lenders': detailed_lender_profiles(),
      'warning':'A published method profile is not a guarantee of a lender-exact payout quote.'}

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

class WorkbenchBody(BaseModel):
    lender: str = Field(min_length=1, max_length=40)
    balance: Decimal = Field(gt=0, le=1_000_000_000)
    contract_rate: Decimal = Field(ge=0, le=30)
    term_start: date
    maturity: date
    payout: date
    current_posted: dict[int, Decimal] = Field(default_factory=dict, max_length=40)
    original_posted_rate: Decimal | None = Field(None, ge=0, le=30)
    contract_discount: Decimal | None = Field(None, ge=0, le=30)
    remaining_amortization_months: int | None = Field(None, ge=1, le=480)
    privilege_available: Decimal = Field(Decimal('0'), ge=0)
    privilege_applicable_to_full_payout: bool = False
    cashback: Decimal = Field(Decimal('0'), ge=0)
    discharge_fee: Decimal = Field(Decimal('0'), ge=0)
    is_open: bool = False
    term_rule_override: TermRule | None = None

@app.get('/api/penalty/v3/methods')
async def penalty_v3_methods():
    return {'methods': all_method_specs(),
            'notice': 'Unverified specs are assumptions; the payout statement is authoritative.'}

@app.post('/api/penalty/v3/workbench')
async def penalty_v3_workbench(body: WorkbenchBody):
    try:
        return run_workbench(WorkbenchCase(**body.model_dump())).as_dict()
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc

from .rates.service import reference_book, workbench_rates, as_strings

@app.get('/api/v5/rates/posted')
async def posted_rate_at(lender: str = Query(min_length=1, max_length=40),
                         term_months: int = Query(ge=1, le=360), on: date = Query(...),
                         allow_proxy: bool = True):
    hit = reference_book().posted_at(lender, term_months, on, allow_proxy=allow_proxy)
    if hit is None:
        raise HTTPException(404, 'No usable posted-rate observation within 120 days of that date')
    return hit.as_dict()

@app.get('/api/v5/rates/table')
async def posted_rate_table(lender: str = Query(min_length=1, max_length=40), on: date = Query(...)):
    table = reference_book().table_at(lender, on)
    return {'lender': lender.lower(), 'on': on.isoformat(),
            'table': {str(k): v.as_dict() for k, v in table.items()},
            'notice': 'Proxy rows are Bank of Canada chartered-bank posted rates, not this lender\'s own figure.'}

@app.get('/api/v5/rates/workbench-inputs')
async def posted_workbench_inputs(lender: str = Query(min_length=1, max_length=40), funded: date = Query(...),
                                  payout: date = Query(...), term_months: int = Query(60, ge=1, le=120)):
    if payout < funded:
        raise HTTPException(422, 'payout is before funding')
    out = workbench_rates(reference_book(), lender, funded, payout, term_months)
    out['original_posted_rate'] = None if out['original_posted_rate'] is None else str(out['original_posted_rate'])
    out['current_posted'] = as_strings(out['current_posted'])
    return out

from .documents.statement import read_statement
from .documents.text import OcrUnavailable, TesseractEngine

def _ocr_engine():
    try:
        return TesseractEngine()
    except OcrUnavailable:
        return None

@app.post('/api/v5/documents/statement')
async def read_mortgage_statement(file: UploadFile = File(...)):
    """Statement or renewal letter (PDF or photo). Bytes are read in memory and discarded."""
    data = await file.read(12 * 1024 * 1024 + 1)
    try:
        return read_statement(data, ocr=_ocr_engine()).as_dict()
    except OcrUnavailable as exc:
        raise HTTPException(422, f'{exc} Upload a text PDF or enter the fields manually.') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

import json as _json
from .banklink.adapters import FlinksAdapter, PlaidAdapter, SandboxTransport
from .banklink.models import CredentialRefused, Provider as LinkProvider, Scope as LinkScope
from .banklink.service import BankLinkService, ConsentError, to_renewal_inputs

_BANKLINK_FIXTURES = Path(__file__).resolve().parent / 'banklink' / 'sandbox'
_banklink: BankLinkService | None = None

def banklink_service() -> BankLinkService:
    """Sandbox-only service; refuses to run unless explicitly enabled."""
    global _banklink
    if os.environ.get('RR_ENABLE_BANKLINK_SANDBOX') != '1':
        raise HTTPException(403, 'Bank linking is not enabled on this server')
    if _banklink is None:
        def load(name):
            return SandboxTransport(_json.loads((_BANKLINK_FIXTURES / f'{name}_sandbox.json').read_text()))
        _banklink = BankLinkService({LinkProvider.PLAID: PlaidAdapter(load('plaid')),
                                     LinkProvider.FLINKS: FlinksAdapter(load('flinks'))})
    return _banklink

class LinkConsentBody(BaseModel):
    subject: str = Field(min_length=1, max_length=64)
    provider: LinkProvider
    purpose: str
    days: int = Field(30, ge=1, le=90)

class LinkCompleteBody(BaseModel):
    public_token: str = Field(min_length=1, max_length=200)
    extra: dict[str, Any] = Field(default_factory=dict)

@app.get('/api/v5/banklink/providers')
async def banklink_providers():
    return {'providers': [p.value for p in LinkProvider], 'credential_collection': False,
            'mode': 'sandbox' if os.environ.get('RR_ENABLE_BANKLINK_SANDBOX') == '1' else 'disabled',
            'notice': 'Connections use the provider-hosted widget. Renewal Radar never sees bank passwords.'}

@app.post('/api/v5/banklink/consents', status_code=201)
async def banklink_consent(body: LinkConsentBody):
    svc = banklink_service()
    try:
        c = svc.grant(body.subject, body.provider, {LinkScope.MORTGAGE_READ}, body.purpose, body.days)
    except (ConsentError, CredentialRefused) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'consent_id': c.id, 'expires_at': c.expires_at.isoformat(), 'scopes': sorted(s.value for s in c.scopes)}

@app.post('/api/v5/banklink/consents/{cid}/session')
async def banklink_session(cid: str):
    try:
        s = banklink_service().start(cid)
    except ConsentError as exc:
        raise HTTPException(403, str(exc)) from exc
    return {'provider': s.provider.value, 'link_token': s.link_token, 'widget_url': s.widget_url,
            'expires_at': s.expires_at.isoformat(), 'sandbox': s.sandbox}

@app.post('/api/v5/banklink/consents/{cid}/complete')
async def banklink_complete(cid: str, body: LinkCompleteBody):
    try:
        return {'link_id': banklink_service().complete(cid, body.public_token, body.extra)}
    except CredentialRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except ConsentError as exc:
        raise HTTPException(403, str(exc)) from exc

@app.get('/api/v5/banklink/links/{link_id}/mortgages')
async def banklink_mortgages(link_id: str, refresh: bool = False):
    try:
        snaps = banklink_service().mortgages(link_id, refresh)
    except ConsentError as exc:
        raise HTTPException(403, str(exc)) from exc
    return {'mortgages': [s.as_dict() for s in snaps], 'prefill': [to_renewal_inputs(s) for s in snaps]}

@app.delete('/api/v5/banklink/consents/{cid}', status_code=204)
async def banklink_revoke(cid: str):
    try:
        banklink_service().revoke(cid)
    except ConsentError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)

# Phase IV: provenance-backed historical rates and tenant-isolated broker tools.
# Neither service pulls third-party bank account data without consent.
from .intelligence.rate_history import RateArchive, RateObservation
from .broker.workspace import BrokerWorkspace, AccessDenied
from pydantic import BaseModel, Field

(ROOT / 'data').mkdir(parents=True, exist_ok=True)
rates_archive = RateArchive(ROOT / 'data' / 'rate-history.sqlite3')
broker_workspace = BrokerWorkspace(ROOT / 'data' / 'broker-workspaces.sqlite3')

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
    if os.environ.get('RR_ENABLE_DEMO_WORKSPACES') != '1':
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

# Broker dashboard: pipeline stages, priorities and follow-up tasks (tenant scoped).
from .broker.dashboard import BrokerDashboard
from .broker.pipeline import InvalidTransition, Stage as BrokerStage


def _market_five_year(lender: str | None, day: date) -> Decimal | None:
    hit = reference_book().posted_at(lender or 'chartered_banks', 60, day)
    return None if hit is None else hit.rate


broker_dashboard = BrokerDashboard(broker_workspace, market_rate=_market_five_year)


class BrokerProfileBody(BaseModel):
    lender: str | None = Field(None, max_length=40)
    balance: Decimal | None = None
    rate_pct: Decimal | None = None
    rate_type: str | None = None


class BrokerStageBody(BaseModel):
    stage: BrokerStage
    note: str = Field('', max_length=500)


class BrokerTaskBody(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    due: date


def _broker_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AccessDenied as exc:
        raise HTTPException(404 if 'not found' in str(exc).lower() else 403, str(exc)) from exc
    except (InvalidTransition, ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/api/v5/broker/workspaces/{wid}/dashboard')
async def broker_dashboard_summary(wid: str, top: int = Query(10, ge=1, le=100),
                                   x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return _broker_call(broker_dashboard.summary, wid, x_broker_token or '', top)


@app.get('/api/v5/broker/workspaces/{wid}/clients/{cid}')
async def broker_client_detail(wid: str, cid: str, x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    token = x_broker_token or ''
    client = _broker_call(broker_dashboard.client, wid, token, cid)
    client['history'] = _broker_call(broker_dashboard.history, wid, token, cid)
    return client


@app.patch('/api/v5/broker/workspaces/{wid}/clients/{cid}/profile')
async def broker_client_profile(wid: str, cid: str, body: BrokerProfileBody,
                                x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return _broker_call(broker_dashboard.update_profile, wid, x_broker_token or '', cid, **body.model_dump())


@app.post('/api/v5/broker/workspaces/{wid}/clients/{cid}/stage')
async def broker_client_stage(wid: str, cid: str, body: BrokerStageBody,
                              x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return _broker_call(broker_dashboard.move, wid, x_broker_token or '', cid, body.stage, body.note)


@app.post('/api/v5/broker/workspaces/{wid}/clients/{cid}/tasks', status_code=201)
async def broker_client_task(wid: str, cid: str, body: BrokerTaskBody,
                             x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return _broker_call(broker_dashboard.add_task, wid, x_broker_token or '', cid, body.kind, body.title, body.due)


@app.post('/api/v5/broker/workspaces/{wid}/tasks/{task_id}/done', status_code=204)
async def broker_task_done(wid: str, task_id: str, x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    _broker_call(broker_dashboard.complete_task, wid, x_broker_token or '', task_id)
    return Response(status_code=204)

# Lead engine: explicit-consent homeowner handoff to a named brokerage.
from .leads.consent import CONSENT_TEXTS, CURRENT_VERSION, ConsentInvalid, validate_consent
from .leads.engine import LeadEngine, LeadInput
from .leads.identity import Vault

LEADS_DB = ROOT / 'data' / 'leads.sqlite3'
_lead_engine: LeadEngine | None = None


def lead_engine() -> LeadEngine:
    """Needs RR_LEAD_KEY (Fernet key) and RR_LEAD_DEDUPE_SECRET (32+ chars); off otherwise."""
    global _lead_engine
    key = os.environ.get('RR_LEAD_KEY', '')
    secret = os.environ.get('RR_LEAD_DEDUPE_SECRET', '')
    if not key or len(secret) < 32:
        raise HTTPException(503, 'Lead handoff is not configured on this server')
    if _lead_engine is None:
        try:
            vault = Vault(key.encode())
        except ValueError as exc:
            raise HTTPException(503, 'Lead encryption key is invalid') from exc
        _lead_engine = LeadEngine(LEADS_DB, vault, secret.encode())
    return _lead_engine


class LeadConsentBody(BaseModel):
    version: str
    text_digest: str
    agreed: bool
    agreed_at: datetime
    contact_methods: list[str]
    brokerage: str = Field(max_length=120)


class LeadBody(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=30)
    province: str = Field(min_length=2, max_length=2)
    renewal_date: date | None = None
    balance: Decimal | None = Field(None, gt=0, le=50_000_000)
    current_rate: Decimal | None = Field(None, ge=0, le=30)
    has_statement: bool = False
    completed_analysis: bool = False
    consent: LeadConsentBody


class LeadWithdrawBody(BaseModel):
    withdraw_token: str = Field(min_length=10, max_length=100)


@app.get('/api/v5/leads/consent-text')
async def lead_consent_text():
    text = CONSENT_TEXTS[CURRENT_VERSION]
    return {'version': text.version, 'text': text.text, 'digest': text.digest}


@app.post('/api/v5/leads', status_code=201)
async def submit_lead(body: LeadBody):
    engine = lead_engine()
    with broker_workspace._db() as db:
        found = db.execute('SELECT 1 FROM broker_workspaces WHERE id=?', (body.workspace_id,)).fetchone()
    if not found:
        raise HTTPException(404, 'Brokerage not found')
    try:
        consent = validate_consent(**body.consent.model_dump(), now=datetime.now(timezone.utc))
        market = reference_book().posted_at('chartered_banks', 60, date.today())
        return engine.submit(LeadInput(
            body.workspace_id, body.name, body.email, body.phone, body.province.upper(), consent,
            body.renewal_date, body.balance, body.current_rate, None if market is None else market.rate,
            body.has_statement, body.completed_analysis))
    except (ConsentInvalid, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete('/api/v5/leads/{lead_id}', status_code=204)
async def withdraw_lead(lead_id: str, body: LeadWithdrawBody):
    try:
        lead_engine().withdraw(lead_id, body.withdraw_token)
    except PermissionError as exc:
        raise HTTPException(404, 'Lead not found') from exc
    return Response(status_code=204)


@app.get('/api/v5/broker/workspaces/{wid}/leads')
async def broker_leads(wid: str, status: str | None = None, x_broker_token: str | None = Header(None)):
    broker_auth(wid, x_broker_token)
    return {'leads': lead_engine().for_broker(wid, status=status),
            'notice': 'Contact details are masked; reveal only when you are about to contact the homeowner.'}


@app.post('/api/v5/broker/workspaces/{wid}/leads/{lead_id}/reveal')
async def broker_reveal_lead(wid: str, lead_id: str, x_broker_token: str | None = Header(None)):
    """Unmask one lead's contact details and record the access in the audit trail."""
    broker_auth(wid, x_broker_token)
    try:
        contact = lead_engine().reveal(wid, lead_id)
    except PermissionError as exc:
        raise HTTPException(404, 'Lead not found') from exc
    with broker_workspace._db() as db:
        broker_workspace._audit(db, wid, None, 'lead_contact_revealed', {'lead_id': lead_id})
    return {'lead_id': lead_id, 'contact': contact}
