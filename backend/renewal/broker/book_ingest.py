"""Broker book ingest: turn exports from broker software, JSON pipelines and OCR'd documents into one deal format.

Column names differ between systems and between brokerages' own report templates, so headers are matched by
meaning (synonyms below), never by position. Every import returns a mapping report: which header fed which field,
which headers were ignored, and which rows could not be used and why. Nothing is guessed: a value that cannot be
read is left empty and the deal is flagged for review.

Supported inputs
  CSV / TSV / semicolon files (Excel "Save as CSV"), any column order, extra columns ignored
  JSON: a list of deal objects, or {"deals": [...]} (e.g. from a CRM/LOS webhook or API pipeline)
  OCR: results of services.document_ocr_v17.read_mortgage_document for PDFs and scans
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from . import book_values as values

# field -> header synonyms (lower-case, punctuation-insensitive). Order inside a list does not matter.
SYNONYMS: dict[str, list[str]] = {
    "deal_id": ["deal id", "deal number", "deal no", "file number", "file no", "application id", "application number",
                "app id", "loan number", "mortgage number", "reference", "ref", "id", "submission id"],
    "borrower": ["borrower", "borrower name", "client", "client name", "primary applicant", "applicant",
                 "applicant name", "customer", "main applicant", "borrowers"],
    "email": ["email", "client email", "borrower email", "applicant email"],
    "phone": ["phone", "client phone", "borrower phone", "mobile", "cell"],
    "lender": ["lender", "lender name", "funder", "funding lender", "institution", "bank", "investor"],
    "product": ["product", "product name", "mortgage product", "program"],
    "rate_type": ["rate type", "interest type", "fixed variable", "fixed/variable", "type of rate", "rate kind"],
    "balance": ["current balance", "outstanding balance", "balance", "principal balance", "remaining balance",
                "loan amount", "mortgage amount", "total mortgage amount", "principal", "funded amount", "amount"],
    "contract_rate": ["contract rate", "interest rate", "rate", "net rate", "client rate", "mortgage rate",
                      "approved rate", "final rate", "actual rate"],
    "posted_rate": ["posted rate", "bank posted rate", "lender posted rate", "posted", "original posted rate"],
    "discount": ["discount", "rate discount", "discount from posted", "rate reduction"],
    "term_months": ["term months", "term (months)", "term in months", "term length months"],
    "term": ["term", "term length", "mortgage term", "term (years)", "term years"],
    "closing_date": ["closing date", "close date", "funding date", "funded date", "advance date", "date funded",
                     "interest adjustment date", "iad", "start date", "commencement date", "approval date",
                     "approved date", "date approved", "completion date"],
    "maturity_date": ["maturity date", "maturity", "renewal date", "term end date", "expiry date", "term expiry"],
    "amort_months": ["amortization months", "amortization (months)", "amort months", "remaining amortization months"],
    "amortization": ["amortization", "amort", "amortization period", "amortization (years)", "amortization years",
                     "remaining amortization"],
    "payment": ["payment", "payment amount", "monthly payment", "regular payment", "p&i", "principal and interest"],
    "frequency": ["payment frequency", "frequency", "pay frequency"],
    "insured": ["insured", "insurance", "cmhc", "default insured", "mortgage insurance", "insurer"],
    "province": ["province", "prov", "property province", "state"],
    "status": ["status", "deal status", "file status", "stage"],
    "balance_date": ["balance date", "statement date", "balance as of"],
}
FIELDS = list(SYNONYMS)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9&/()]+", " ", (h or "").lower()).strip()


def map_headers(headers: list[str], overrides: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """{field: header}. Exact synonym match first, then 'contains' match; each header used once."""
    overrides = overrides or {}
    mapping, used = {}, set()
    for f, h in overrides.items():
        if f in SYNONYMS and h in headers:
            mapping[f] = h
            used.add(h)
    normed = {h: _norm(h) for h in headers}
    for exact in (True, False):
        for f, syns in SYNONYMS.items():
            if f in mapping:
                continue
            candidates = headers
            if f == "balance":
                candidates = sorted(headers, key=lambda h: (
                    0 if any(w in normed[h] for w in ("current balance", "outstanding", "remaining balance")) else 1,
                    headers.index(h),
                ))
            for h in candidates:
                if h in used:
                    continue
                n = normed[h]
                hit = n in syns if exact else any(len(s) > 3 and (s in n) for s in syns)
                if hit:
                    mapping[f] = h
                    used.add(h)
                    break
    return mapping, [h for h in headers if h not in used]


# ---------------- value parsing (strict: unreadable -> None) ----------------
def parse_date(v, prefer_day_first=None) -> date | None:
    order = "day_first" if prefer_day_first is True else "month_first" if prefer_day_first is False else None
    return values.read_date(v, order).value


def parse_money(v) -> float | None:
    return values.money(v)


def parse_rate(v) -> float | None:
    return values.percentage(v)


def parse_months(v, unit_hint: str = "") -> int | None:
    return values.duration(v, unit_hint)


def parse_amort(v, unit_hint: str = "") -> int | None:
    return values.duration(v, unit_hint, amortization=True)


def parse_rate_type(v) -> str | None:
    return values.rate_kind(v)


def parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    if s in ("y", "yes", "true", "1", "insured", "cmhc", "sagen", "canada guaranty", "genworth"):
        return True
    if s in ("n", "no", "false", "0", "uninsured", "conventional"):
        return False
    return None


# ---------------- the deal record ----------------
@dataclass
class Deal:
    deal_id: str
    borrower: str | None = None
    email: str | None = None
    phone: str | None = None
    lender: str | None = None
    product: str | None = None
    rate_type: str | None = None
    balance: float | None = None
    contract_rate: float | None = None
    posted_rate: float | None = None
    discount: float | None = None
    term_months: int | None = None
    closing_date: date | None = None
    maturity_date: date | None = None
    amort_months: int | None = None
    payment: float | None = None
    frequency: str | None = None
    insured: bool | None = None
    province: str | None = None
    status: str | None = None
    balance_basis: str = "current"        # current (outstanding today) | original (loan amount at closing)
    source: str = "csv"
    issues: list[str] = field(default_factory=list)
    balance_date: date | None = None
    amort_basis: str = "remaining"
    is_open: bool | None = None
    review_confirmed: bool = False
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("closing_date", "maturity_date", "balance_date"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


def _finish(d: Deal) -> Deal:
    """Derive what can be derived exactly; flag what is missing or inconsistent."""
    from ..ratewatch.ird import add_months
    if d.maturity_date is None and d.closing_date and d.term_months:
        d.maturity_date = add_months(d.closing_date, d.term_months)
    if d.term_months is None and d.closing_date and d.maturity_date:
        months = (d.maturity_date.year - d.closing_date.year) * 12 + d.maturity_date.month - d.closing_date.month
        d.term_months = months if months > 0 else None
    if d.discount is None and d.posted_rate is not None and d.contract_rate is not None:
        d.discount = round(d.posted_rate - d.contract_rate, 4) if d.posted_rate >= d.contract_rate else None
    for f in ("lender", "balance", "contract_rate", "closing_date", "maturity_date"):
        if getattr(d, f) in (None, ""):
            d.issues.append(f"missing {f.replace('_', ' ')}")
    if d.closing_date and d.maturity_date and d.maturity_date <= d.closing_date:
        d.issues.append("maturity is not after closing")
    if d.rate_type is None:
        d.issues.append("rate type not stated: confirmation required")
    d.issues = list(dict.fromkeys(d.issues))
    return d


def _deal_from_row(row: dict, mapping: dict[str, str], n: int, source: str, day_first: bool) -> Deal:
    get = lambda f: row.get(mapping[f]) if f in mapping else None
    hint = lambda f: _norm(mapping.get(f, ""))
    term = parse_months(get("term_months"), "month") if "term_months" in mapping else parse_months(get("term"), hint("term"))
    amort = parse_amort(get("amort_months"), "month") if "amort_months" in mapping else parse_amort(get("amortization"), hint("amortization"))
    basis = row.get("balance_basis") or _balance_basis(mapping.get("balance"))
    amort_hint = hint("amort_months") if "amort_months" in mapping else hint("amortization")
    amort_basis = row.get("amort_basis") or (
        "remaining" if "remaining" in amort_hint else "original" if basis == "original" else "remaining"
    )
    d = Deal(
        deal_id=str(get("deal_id") or f"row-{n}").strip(),
        borrower=(str(get("borrower")).strip() or None) if get("borrower") else None,
        email=(str(get("email")).strip() or None) if get("email") else None,
        phone=(str(get("phone")).strip() or None) if get("phone") else None,
        lender=(str(get("lender")).strip() or None) if get("lender") else None,
        product=(str(get("product")).strip() or None) if get("product") else None,
        rate_type=parse_rate_type(get("rate_type")) or parse_rate_type(get("product")),
        balance=parse_money(get("balance")), contract_rate=parse_rate(get("contract_rate")),
        posted_rate=parse_rate(get("posted_rate")), discount=_parse_discount(get("discount")),
        term_months=term, closing_date=parse_date(get("closing_date"), day_first),
        maturity_date=parse_date(get("maturity_date"), day_first), amort_months=amort,
        payment=parse_money(get("payment")), frequency=(str(get("frequency")).strip() or None) if get("frequency") else None,
        insured=parse_bool(get("insured")), province=(str(get("province")).strip() or None) if get("province") else None,
        status=(str(get("status")).strip() or None) if get("status") else None,
        balance_basis=basis, source=source,
        balance_date=parse_date(get("balance_date"), day_first),
        amort_basis=amort_basis,
        is_open=values.contract_is_open(get("product")),
    )
    d.frequency = values.payment_frequency(d.frequency) or d.frequency
    for name in ("balance", "contract_rate", "posted_rate", "discount", "term_months", "amort_months", "payment"):
        raw_name = "term" if name == "term_months" and "term" in mapping else (
            "amortization" if name == "amort_months" and "amortization" in mapping else name
        )
        if get(raw_name) not in (None, "") and getattr(d, name) is None:
            d.issues.append(f"invalid {name.replace('_', ' ')}: correct the source value")
    for name in ("closing_date", "maturity_date", "balance_date"):
        if get(name) not in (None, "") and getattr(d, name) is None:
            d.issues.append(f"ambiguous or invalid {name.replace('_', ' ')}: choose an explicit date format")
    return _finish(d)


def _balance_basis(header: str | None) -> str:
    """'Current balance', 'Outstanding' -> current; 'Loan amount', 'Mortgage amount', 'Funded amount' -> original."""
    n = _norm(header or "")
    if "original" in n:
        return "original"
    if any(w in n for w in ("current", "outstanding", "remaining", "balance")):
        return "current"
    return "original" if n else "current"


def _parse_discount(v) -> float | None:
    return values.percentage(v, fraction_allowed=False, allow_zero=True, maximum=10)


MAX_ROWS = 20000
MAX_BYTES = 20 * 1024 * 1024


def import_csv(data: bytes | str, overrides: dict[str, str] | None = None, source: str = "csv",
               date_order: str | None = None) -> dict:
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise ValueError("file larger than 20 MB")
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    else:
        text = data
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise ValueError("no header row found")
    rows = []
    for i, r in enumerate(reader):
        if i >= MAX_ROWS:
            raise ValueError(f"more than {MAX_ROWS} rows; split the file")
        if any((v or "").strip() for v in r.values() if isinstance(v, str)):
            rows.append(r)
    mapping, ignored = map_headers(headers, overrides)
    order, conflict = values.infer_date_order(
        r.get(mapping[f]) for r in rows for f in ("closing_date", "maturity_date") if f in mapping
    )
    if date_order not in (None, "day_first", "month_first"):
        raise ValueError("date_order must be day_first or month_first")
    if conflict and date_order is None:
        raise ValueError("conflicting date formats: choose date_order or normalize the export")
    order = date_order or order
    day_first = True if order == "day_first" else False if order == "month_first" else None
    deals = [_deal_from_row(r, mapping, n, source, day_first) for n, r in enumerate(rows, start=2)]
    return {"deals": [d.as_dict() for d in deals], "mapping": mapping, "ignored_columns": ignored,
            "unmapped_fields": [f for f in ("lender", "balance", "contract_rate", "closing_date", "term", "maturity_date")
                                if f not in mapping and not (f == "term" and "term_months" in mapping)],
            "date_order": "day/month/year" if day_first else "month/day/year" if day_first is False else "ISO or explicit confirmation",
            "rows": len(rows), "with_issues": sum(1 for d in deals if d.issues)}


def import_json(data: bytes | str, overrides: dict[str, str] | None = None) -> dict:
    obj = json.loads(data)
    items = obj.get("deals", obj.get("data", [])) if isinstance(obj, dict) else obj
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise ValueError("expected a list of deal objects or {\"deals\": [...]}")
    if len(items) > MAX_ROWS:
        raise ValueError(f"more than {MAX_ROWS} deals")
    headers = sorted({k for it in items for k in it})
    flat = [{k: ("" if v is None else v) for k, v in it.items()} for it in items]
    mapping, ignored = map_headers(headers, overrides)
    order, conflict = values.infer_date_order(
        r.get(mapping[f]) for r in flat for f in ("closing_date", "maturity_date") if f in mapping
    )
    if conflict:
        raise ValueError("conflicting date formats in JSON")
    day_first = True if order == "day_first" else False if order == "month_first" else None
    deals = [_deal_from_row(r, mapping, n, "json", day_first) for n, r in enumerate(flat, start=1)]
    return {"deals": [d.as_dict() for d in deals], "mapping": mapping, "ignored_columns": ignored,
            "rows": len(deals), "with_issues": sum(1 for d in deals if d.issues)}


def deal_from_ocr(result: dict, deal_id: str, lender: str | None = None, closing_date: str | None = None) -> dict:
    """OCR result (read_mortgage_document) -> deal. OCR readings always carry a 'verify against the document' issue."""
    f = {k: v.get("value") for k, v in (result.get("fields") or {}).items()}
    d = _finish(Deal(deal_id=deal_id, lender=lender, balance=parse_money(f.get("balance")),
                     contract_rate=parse_rate(f.get("current_rate") or f.get("offered_rate")),
                     term_months=parse_months(f.get("term_months"), "month"),
                     maturity_date=parse_date(f.get("maturity_date")), closing_date=parse_date(closing_date),
                     amort_months=parse_amort(f.get("amortization_months"), "month"),
                     frequency=f.get("frequency"), source="ocr"))
    d.issues.insert(0, "read by OCR: verify every value against the document")
    out = d.as_dict()
    out["evidence"] = {k: {"page": v.get("page"), "excerpt": v.get("excerpt")} for k, v in (result.get("fields") or {}).items()}
    return out


def deal_from_dict(d: dict) -> Deal:
    """Re-hydrate a (possibly broker-edited) deal dict."""
    known = {k: d.get(k) for k in Deal.__dataclass_fields__ if k in d}
    preserved = known.get("issues") or []
    known["issues"] = [str(i)[:250] for i in preserved[:40]] if isinstance(preserved, list) else []
    for k in ("closing_date", "maturity_date", "balance_date"):
        known[k] = parse_date(known.get(k)) if known.get(k) else None
    for k in ("balance", "payment"):
        if known.get(k) is not None:
            known[k] = parse_money(known[k])
    for k in ("contract_rate", "posted_rate"):
        if known.get(k) is not None:
            known[k] = values.percentage(known[k], fraction_allowed=False)
    if known.get("discount") is not None:
        known["discount"] = _parse_discount(known["discount"])
    for k, parser in (("term_months", parse_months), ("amort_months", parse_amort)):
        if known.get(k) is not None:
            raw = known[k]
            known[k] = parser(raw, "month")
            if known[k] is None:
                known["issues"].append(f"invalid {k.replace('_', ' ')}")
    for k in ("borrower", "email", "phone", "lender", "product", "province", "status"):
        known[k] = values.clean_text(known.get(k), 160)
    known["deal_id"] = values.clean_text(known.get("deal_id"), 120) or "deal"
    kind = known.get("rate_type")
    known["rate_type"] = parse_rate_type(kind) or parse_rate_type(known.get("product"))
    if kind and known["rate_type"] is None:
        known["issues"].append("invalid rate type")
    if known.get("frequency"):
        known["frequency"] = values.payment_frequency(known["frequency"]) or str(known["frequency"])[:60]
    known["is_open"] = parse_bool(known.get("is_open"))
    known["review_confirmed"] = known.get("review_confirmed") is True
    if not isinstance(known.get("evidence"), dict):
        known["evidence"] = {}
    if known.get("source") not in ("csv", "json", "ocr", "manual", None):
        known["source"] = "manual"
    known.setdefault("balance_basis", "current")
    known.setdefault("amort_basis", "original" if known["balance_basis"] == "original" else "remaining")
    known.setdefault("deal_id", "deal")
    return _finish(Deal(**known))
