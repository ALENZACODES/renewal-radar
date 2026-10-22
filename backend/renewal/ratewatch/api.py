"""HTTP endpoints for ratewatch: live lender rates, TD-exact penalty, forecast, backtest report, PDF letter."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ird import Mortgage, POLICIES, forecast, penalty
from .paths import DATA

router = APIRouter(prefix="/api/ratewatch", tags=["ratewatch"])
SOURCES = {"rbc": "P021", "td": "P023", "scotiabank": "P025", "bmo": "P027", "cibc": "P029",
           "national bank": "P031", "simplii": "P034", "atb": "P039", "desjardins": "P035", "tangerine": "P033"}
POLICY_NAMES = {k: next((p for p in POLICIES if p.lower() == k), None) for k in SOURCES}


class PenaltyIn(BaseModel):
    """Closed fixed-rate mortgages only. Unknown fields are rejected so nothing is silently ignored."""
    model_config = ConfigDict(extra="forbid")
    lender: str = Field(examples=["TD"])
    rate_type: str = Field(default="fixed", description="only 'fixed' is supported")
    is_open: bool = Field(default=False, description="open mortgages have no prepayment charge model here")
    balance: float = Field(gt=0, le=1e9)
    contract_rate: float = Field(gt=0, le=30)
    term_months: int = Field(gt=0, le=360)
    start: date
    maturity: date | None = None
    discount: float | None = Field(default=None, ge=0, le=10)
    posted_at_origination: float | None = Field(default=None, gt=0, le=30)
    payout: date | None = None
    amort_months: int = Field(default=300, gt=0, le=480, description="remaining amortization in months (from the statement)")
    current_posted: dict[int, float] | None = None        # override the live table, e.g. {"24": 5.29}

    @field_validator("rate_type")
    @classmethod
    def _fixed_only(cls, v):
        if v != "fixed":
            raise ValueError("only closed fixed-rate mortgages are supported; variable-rate charges are not modelled here")
        return v

    @field_validator("is_open")
    @classmethod
    def _closed_only(cls, v):
        if v:
            raise ValueError("open mortgages are not modelled here (they normally carry no prepayment charge)")
        return v

    @field_validator("current_posted")
    @classmethod
    def _table_ok(cls, v):
        if v is not None:
            if not v:
                raise ValueError("current_posted is empty")
            for t, r in v.items():
                if t not in (6, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120):
                    raise ValueError(f"unsupported term {t} months in current_posted")
                if not 0 < r <= 30:
                    raise ValueError(f"rate {r} for {t} months must be between 0 and 30")
        return v

    @model_validator(mode="after")
    def _dates_ok(self):
        from datetime import timedelta
        if not date(1990, 1, 1) <= self.start <= date.today() + timedelta(days=366):
            raise ValueError("start date out of range")
        if self.maturity is not None and not (self.start < self.maturity <= self.start + timedelta(days=366 * 11)):
            raise ValueError("maturity must be after start and within 10 years of it")
        if self.payout is not None and not (self.start <= self.payout <= date.today() + timedelta(days=366 * 11)):
            raise ValueError("payout must be on or after the start date and not far in the future")
        return self


def _live_table(lender: str):
    from .scrape import fetch
    sid = SOURCES.get(lender.lower())
    if not sid:
        raise HTTPException(404, f"no live source for {lender}; pass current_posted")
    rows, how = fetch(sid)
    table = {t: r for t, k, rt, r in rows if k == "fixed_closed" and rt == "posted"}
    if not table:
        raise HTTPException(502, f"{lender} rates unavailable right now; pass current_posted")
    return table, how


def _policy(lender: str):
    from .accuracy import policy_for
    name = POLICY_NAMES.get(lender.lower()) or lender
    return policy_for(name)


def _historical_table(lender: str, day: date):
    from . import history
    sid = SOURCES.get(lender.lower())
    table, seen = history.table_on(sid, day, max_age_days=10) if sid else ({}, None)
    if not table:
        raise HTTPException(422, f"no recorded {lender} posted rates near {day}; pass current_posted for a past payout")
    how = history.provenance(sid, day, max_age_days=10)
    if how in history.FILL_HOWS:
        return table, f"history ({seen}; {history.FILL_LABEL[how]})"
    return table, f"history ({seen})"


def _check_table(table: dict, how: str):
    """Same rules for every table, whoever produced it: supported terms, rates strictly 1-15%."""
    bad = {t: r for t, r in table.items() if not (isinstance(r, (int, float)) and 1.0 <= r <= 15.0)}
    if not table or bad:
        raise HTTPException(502 if how not in ("supplied",) else 422,
                            f"rate table from {how} failed validation: {bad or 'empty'}; no calculation made")
    return table


def _run(body: PenaltyIn):
    payout = body.payout or date.today()
    if payout < body.start:
        raise HTTPException(422, "the mortgage has not started on the payout date (payout before start)")
    if body.current_posted:
        table, how = {int(k): v for k, v in body.current_posted.items()}, "supplied"
    elif payout < date.today():
        table, how = _historical_table(body.lender, payout)      # never today's rates for a past date
    else:
        table, how = _live_table(body.lender)
    _check_table(table, how)
    m = Mortgage(body.balance, body.contract_rate, body.term_months, body.start,
                 {body.term_months: body.posted_at_origination} if body.posted_at_origination else {},
                 body.discount, amort_months=body.amort_months, maturity=body.maturity)
    pol = _policy(body.lender)
    try:
        return m, pol, table, payout, how, penalty(m, pol, table, payout)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/rates/{lender}")
def rates(lender: str):
    from .scrape import fetch
    sid = SOURCES.get(lender.lower())
    if not sid:
        raise HTTPException(404, "unknown lender")
    rows, how = fetch(sid)
    return {"lender": lender, "source": how, "as_of": date.today().isoformat(),
            "rates": [{"term_months": t, "kind": k, "type": rt, "rate": r} for t, k, rt, r in rows]}


@router.post("/penalty")
def penalty_endpoint(body: PenaltyIn):
    _, pol, table, _, how, result = _run(body)
    return {**result, "rates_source": how, "status": "exact-method" if pol.verified else "estimate"}


@router.post("/forecast")
def forecast_endpoint(body: PenaltyIn):
    m, pol, table, payout, _, _ = _run(body)
    rows = forecast(m, pol, table, payout, step_days=7)
    return {"transitions": [r for r in rows if r["transition"]], "weekly": rows}


@router.get("/backtest")
def backtest_report():
    f = DATA / "backtest_report.json"
    if not f.exists():
        raise HTTPException(404, "run python -m renewal.ratewatch.backtest first")
    return json.loads(f.read_text())


class LetterIn(PenaltyIn):
    client_name: str = Field(default="Homeowner", max_length=120)    # in the body, never the URL (URLs reach access logs)
    language: str = Field(default="en", pattern="^(en|fr)$")


@router.post("/letter")
def letter(body: LetterIn):
    """Builds the PDF entirely in memory: client details are never written to disk or to URLs/logs."""
    client_name, language = body.client_name, body.language
    from io import BytesIO
    from .letter import build_letter
    m, pol, table, payout, _, result = _run(body)
    if result["method"] == "matured":
        raise HTTPException(422, "term has matured: there is no prepayment charge")
    rows = forecast(m, pol, table, payout, step_days=7)
    buf = BytesIO()
    build_letter(buf, {"name": client_name, "address_lines": []},
                 {"lender": body.lender, "balance": body.balance, "contract_rate": body.contract_rate},
                 result, rows, lender_verified=pol.verified, language=language)
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="penalty-assessment.pdf"',
                             "Cache-Control": "no-store"})


# ---------------- Decision helpers (extras.py) ----------------
class ExtrasIn(PenaltyIn):
    new_rate: float | None = Field(default=None, gt=0, le=30)
    fees: float = Field(default=0.0, ge=0)
    new_term_months: int = Field(default=60, gt=0, le=360)
    allowance_pct: float = Field(default=15.0, ge=0, le=100)
    original_amount: float | None = Field(default=None, gt=0)
    quoted_penalty: float | None = Field(default=None, gt=0)
    port_fee: float = Field(default=0.0, ge=0)
    language: str = Field(default="en", pattern="^(en|fr)$")


@router.post("/extras/{tool}")
def extras_endpoint(tool: str, body: ExtrasIn):
    from . import extras as x
    m, pol, table, payout, _, result = _run(body)
    if tool in ("break-even", "blend", "net-switch") and body.new_rate is None:
        raise HTTPException(422, "new_rate is required for this tool")
    if tool == "reverse-rate" and body.quoted_penalty is None:
        raise HTTPException(422, "quoted_penalty is required for this tool")
    tools = {
        "break-even": lambda: x.break_even(m, pol, table, payout, body.new_rate, body.fees, body.new_term_months),
        "cheapest-day": lambda: x.cheapest_day(m, pol, table, payout),
        "blend": lambda: x.blend_and_extend(m, payout, body.new_rate, body.new_term_months, pol, table),
        "lump-sum": lambda: x.lump_sum_first(m, pol, table, payout, body.allowance_pct, body.original_amount),
        "sensitivity": lambda: x.sensitivity(m, pol, table, payout),
        "port-vs-break": lambda: x.port_vs_break(m, pol, table, payout, body.port_fee),
        "countdown": lambda: x.renewal_countdown(m, payout),
        "stress-test": lambda: x.stress_test(body.balance, body.contract_rate),
        "net-switch": lambda: x.net_switch_benefit(m, pol, table, payout, body.new_rate, body.fees, new_term_months=body.new_term_months),
        "reverse-rate": lambda: x.reverse_rate(m, pol, payout, body.quoted_penalty),
        "heatmap": lambda: x.heatmap(m, pol, table, payout),
        "summary": lambda: {"text": x.summary_text(body.lender, result, x.cheapest_day(m, pol, table, payout), body.language)},
    }
    if tool == "csv":
        csv_text = x.to_csv(result, forecast(m, pol, table, payout, step_days=7))
        return Response(csv_text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="penalty.csv"'})
    if tool not in tools:
        raise HTTPException(404, f"unknown tool; choose from {sorted(tools) + ['csv']}")
    return tools[tool]()


# ---------------- Live rates board (live.py): big banks + credit unions, primary + 3 backups ----------------
@router.get("/live")
def live_board():
    from . import live
    return live.board(wait=False)


@router.post("/live/refresh")
def live_refresh():
    from . import live
    return live.refresh()


# ---------------- CSV batch ingest (strict RateRow + quarantine + last-good) ----------------
@router.post("/batches/csv", status_code=201)
async def import_rate_csv(
    file: UploadFile = File(...),
    x_rate_ingest_key: str | None = Header(default=None),
):
    """Ingest a Ratewatch rates CSV. Whole-batch quarantine on any defect or sanity failure.

    Requires `X-Rate-Ingest-Key` / `RR_RATE_INGEST_KEY` (min 24 chars).
    Same SHA-256 as the active batch is a no-op. Bad imports never move last-good.
    """
    import os
    import secrets

    key = os.environ.get('RR_RATE_INGEST_KEY', '')
    if len(key) < 24 or not secrets.compare_digest(x_rate_ingest_key or '', key):
        raise HTTPException(403, 'Rate CSV ingest unavailable without configured ingest key')
    from .batch_store import default_store
    from .csv_batch import MAX_BYTES

    raw = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f'CSV must be smaller than {MAX_BYTES // (1024 * 1024)} MB')
    result = default_store.import_csv(raw, source=file.filename or 'upload')
    status = result.get('status')
    code = 201 if status in {'active', 'noop'} else 422
    return JSONResponse(result, status_code=code)


@router.get("/batches/active")
def active_rate_batch():
    """Readers see only the active batch pointer (never quarantined drafts)."""
    from .batch_store import default_store
    from .csv_batch import HEADERS

    ptr = default_store.pointer()
    rows = default_store.active_rows()
    return {
        'pointer': ptr,
        'headers': list(HEADERS),
        'rows': [r.as_dict() for r in rows],
        'notice': 'Active Ratewatch CSV batch only; quarantined imports are excluded.',
    }


@router.get("/batches/quarantine")
def list_quarantined_batches(limit: int = 25):
    from .batch_store import default_store
    return {'events': default_store.list_quarantine(limit=max(1, min(limit, 100)))}


@router.get("/batches/last-good")
def last_good_rate_batch_meta():
    """Metadata for the last-good pointer (not truncated on quarantine)."""
    from .batch_store import default_store
    return {'last_good': default_store.last_good()}
