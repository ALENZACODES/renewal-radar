# Live rates: complete code

*Renewal Radar · John Khan*

Generated from the source files in this repository (do not edit here; edit the files listed).
Run: `cd backend && python -m renewal.ratewatch.live` or open the app's **Live rates** page.

Also wired in: `frontend/index.html` (nav entries), `frontend/js/views.js` (page), `frontend/js/app.js`
(actions `live-rates-refresh`), `frontend/js/api.js` (`liveRates`, `liveRatesRefresh`), `frontend/service-worker.js` (offline cache).

## Engine: sources, 3 backups, validation, cache, board
`backend/renewal/ratewatch/live.py` (361 lines)

```python
"""Live current rates board: big banks and credit unions, primary source + 3 backups per lender.

    python -m renewal.ratewatch.live          refresh now and print the board
    GET  /api/ratewatch/live                  board (served from the last refresh; refreshes in the background if stale)
    POST /api/ratewatch/live/refresh          refresh now

For every lender, sources are tried in order until one passes validation:
    primary   the lender's own data feed or rates page
    backup 1  a second live source from the same lender (French page / other feed), else automatic rediscovery
              of the lender's moved rates page on its own site
    backup 2  the last good reading saved by this module (at most CACHE_DAYS old, shown with its age)
    backup 3  the newest web-archive copy of the lender's own page or feed (Wayback, then Common Crawl)
If all four fail for a big bank, the board shows the Bank of Canada big-six typical posted rate, labelled as not
lender-specific. Nothing is ever estimated or invented; a lender with no valid reading is shown as unavailable.
"""
from __future__ import annotations

import gzip
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from . import history, scrape
from .linkcheck import UA
from .parse import extract_rates
from .paths import DATA

CACHE = DATA / "live_cache.json"
BOARD = DATA / "live_board.json"
CACHE_DAYS = 14
STALE_AFTER = timedelta(hours=6)
TIMEOUT = 20
TIER_LABEL = {"primary": "Live", "backup1": "Live (backup source)", "cache": "Last good reading",
              "archive": "Archive copy", "boc_typical": "Bank of Canada big-six typical", "unavailable": "Unavailable"}

# id, name, type, primary (kind, url), backup1 (kind, url) or None -> rediscovery
LENDERS = [
    ("P021", "RBC", "bank", ("html", "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html"), None),
    ("P023", "TD", "bank", ("td_api", "https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates"),
     ("td_json", "https://ix0.apps.td.com/api/get-rates/en")),
    ("P025", "Scotiabank", "bank", ("scotia_api", "https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage"), None),
    ("P027", "BMO", "bank", ("bmo_api", "https://www.bmo.com/public-data/api/epm/v1.0/bmo-epm-mortgage.json"), None),
    ("P029", "CIBC", "bank", ("cibc_api", "https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2c5YRVARCLO%2cFOM%2cVROM%2c"),
     ("cibc_js", "https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode=FRCM%2c")),
    ("P031", "National Bank", "bank", ("html", "https://www.nbc.ca/personal/mortgages/rates.html"),
     ("html", "https://www.bnc.ca/particuliers/hypotheque/taux.html")),
    ("P035", "Desjardins", "credit_union", ("html", "https://www.desjardins.com/en/mortgage/mortgage-rates.html"),
     ("html", "https://www.desjardins.com/fr/hypotheque/taux-hypothecaires.html")),
    ("CU01", "Meridian", "credit_union", ("html", "https://www.meridiancu.ca/personal/rates-and-fees/mortgage-and-borrowing-rates"), None),
    ("CU02", "Vancity", "credit_union", ("html", "https://www.vancity.com/rates/mortgages"), None),
    ("CU03", "Coast Capital", "credit_union", ("html", "https://www.coastcapitalsavings.com/rates"), None),
    ("CU04", "Servus", "credit_union", ("html", "https://servus.ca/rates"), None),
    ("CU05", "Alterna Savings", "credit_union", ("html", "https://www.alterna.ca/en/rates/mortgages"), None),
    ("CU06", "DUCA", "credit_union", ("html", "https://www.duca.com/rates"), None),
    ("CU07", "FirstOntario", "credit_union", ("html", "https://www.firstontario.com/personal/rates/"), None),
    ("CU08", "Libro", "credit_union", ("html", "https://www.libro.ca/rates-fees/mortgage/"), None),
    ("CU09", "Affinity", "credit_union", ("html", "https://www.affinitycu.ca/rates/mortgage-rates"), None),
    ("CU10", "Conexus", "credit_union", ("html", "https://www.conexus.ca/rates/mortgage-rates"), None),
    ("CU11", "Your Neighbourhood CU", "credit_union", ("html", "https://www.yncu.com/resources/rates/mortgage-rates"), None),
    ("CU12", "Synergy", "credit_union", ("html", "https://www.synergycu.ca/en/rates/mortgages"), None),
    ("CU13", "Coastal Community", "credit_union", ("html", "https://cccu.ca/financial-tools/rates/mortgage-rates/"), None),
    ("CU14", "Access Credit Union", "credit_union", ("html", "https://www.accesscu.ca/en/rates"), None),
    ("CU15", "beem", "credit_union", ("html", "https://beemcreditunion.ca/rates"), None),
    ("CU16", "Mainstreet", "credit_union", ("html", "https://mainstreetcu.ca/rates"), None),
    ("CU17", "Innovation", "credit_union", ("html", "https://www.innovationcu.ca/personal/borrowing/mortgage-rates.html"), None),
    ("CU18", "Kawartha", "credit_union", ("html", "https://www.kawarthacu.com/rates"), None),
    ("CU19", "Steinbach", "credit_union", ("html", "https://scu.mb.ca/rates"), None),
    ("CU20", "Tandia", "credit_union", ("html", "https://www.tandia.com/rates"), None),
]


# ---------------- readers ----------------
def _http(url, **kw):
    return requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=TIMEOUT, **kw)


def read_live(kind: str, url: str) -> list:
    """Fetch and parse one live source. Raises on network failure; returns [] when nothing parses."""
    if kind == "td_api":
        return scrape.td()
    if kind == "scotia_api":
        return scrape.scotia()
    if kind == "bmo_api":
        return scrape.bmo_posted_rows(_http(url).json())
    if kind == "cibc_api":
        return scrape.cibc()
    return parse_text(kind, _http(url, headers={"Referer": url}).text)


def parse_text(kind: str, text: str) -> list:
    """Parse a live response or an archived copy of the same source."""
    from .backfill import parse as parse_feed
    if kind in ("html",):
        return extract_rates(text)
    if kind in ("td_api",):
        return []                                             # TD's live feed is a POST; archives cannot hold it
    if kind in ("scotia_api", "scotia_json"):
        return parse_feed("scotia_json", text)
    if kind in ("bmo_api", "bmo_epm"):
        return parse_feed("bmo_epm", text)
    if kind in ("cibc_api", "cibc_js"):
        return scrape.cibc_rows(text)
    if kind == "td_json":
        return parse_feed("td_json", text)
    return extract_rates(text)


def read_archive(kind: str, url: str) -> tuple[list, str | None]:
    """Newest archived copy of the lender's own source: Wayback (<=CACHE_DAYS old), then Common Crawl.
    Returns (rows, note); when rows is empty, note explains why."""
    reason = "no archive copy"
    try:
        r = _http(f"https://web.archive.org/web/2id_/{url}")
        ts = r.url.split("/web/")[1][:14] if "/web/" in r.url else None
        if r.status_code == 429:
            reason = "web archive is rate-limiting requests"
        elif not r.ok or not ts:
            reason = f"web archive returned {r.status_code}"
        elif datetime.strptime(ts[:8], "%Y%m%d") < datetime.now() - timedelta(days=CACHE_DAYS):
            reason = f"newest web-archive copy ({ts[:8]}) is older than {CACHE_DAYS} days"
        else:
            rows = parse_text(kind, r.text)
            if rows:
                return rows, f"wayback {ts[:8]}"
            reason = f"web-archive copy {ts[:8]} holds no rates"
    except (requests.RequestException, ValueError, IndexError) as e:
        reason = f"web archive unreachable ({type(e).__name__})"
    rows, ts = scrape.commoncrawl_latest(url, max_age_days=CACHE_DAYS)
    return (rows, f"common crawl {ts[:8]}") if rows else ([], reason + "; no recent Common Crawl copy")


def read_rediscovered(url: str) -> tuple[list, str | None]:
    try:
        return scrape.rediscovered(url)
    except Exception:
        return [], None


# ---------------- validation ----------------
def market_anchor() -> dict:
    """Bank of Canada figures used to sanity-check every reading."""
    out = {}
    try:
        from .validate import boc_latest
        out["boc_5y_posted_date"], out["boc_5y_posted"] = boc_latest("V80691335")
        out["goc_5y_date"], out["goc_5y"] = boc_latest("BD.CDN.5YR.DQ.YLD")
    except Exception:
        t, day = history.table_on("BIG6_TYPICAL", datetime.now().date(), max_age_days=14)
        g, _ = history.table_on("GOC", datetime.now().date(), rtype="yield", kind="bond", max_age_days=14)
        out = {"boc_5y_posted": t.get(60), "boc_5y_posted_date": day, "goc_5y": g.get(60)}
    return out


def summarize(rows: list) -> dict:
    by_term = {}
    for t, k, rt, r in rows:
        if k == "fixed_closed" and rt in ("posted", "special"):
            by_term.setdefault(t, {}).setdefault(rt, r)
    return by_term


ABS_MIN, ABS_MAX = 1.0, 15.0          # no Canadian mortgage rate outside this range is accepted, anchor or not


def validate(rows: list, lender_type: str, anchor: dict) -> tuple[bool, str]:
    """Fails closed: every rate shown must be plausible, not just the 5-year one."""
    terms = summarize(rows)
    five = terms.get(60, {})
    if not five:
        return False, "no 5-year fixed rate found"
    for t, v in terms.items():
        for rt, r in v.items():
            if not ABS_MIN <= r <= ABS_MAX:
                return False, f"{t}-month {rt} rate {r} outside {ABS_MIN}-{ABS_MAX}%"
    if anchor.get("goc_5y") is None or (lender_type == "bank" and anchor.get("boc_5y_posted") is None):
        return False, "Bank of Canada reference figures unavailable; cannot validate"
    for t, v in terms.items():
        if "posted" in v and "special" in v and t >= 36 and v["special"] > v["posted"] + 0.01:
            return False, f"{t}-month special above posted (labels likely swapped)"
    goc = anchor.get("goc_5y")
    if lender_type == "bank":
        boc = anchor.get("boc_5y_posted")
        if "posted" not in five:
            return False, "no 5-year posted rate"
        if boc is not None and abs(five["posted"] - boc) > 0.75:
            return False, f"5-year posted {five['posted']} is far from the big-six typical {boc}"
        return True, "ok"
    for t, v in terms.items():                  # other terms: same plausible band around the 5-year bond
        for rt, r in v.items():
            if not goc - 0.5 <= r <= goc + 6.5:
                return False, f"{t}-month {rt} rate {r} implausible against a 5-year bond at {goc}"
    advertised = min(five.values())
    if not (goc + 0.3 <= advertised <= goc + 4.5):
        return False, f"5-year rate {advertised} outside the plausible band for a 5-year bond at {goc}"
    return True, "ok"


# ---------------- cache ----------------
_lock = threading.Lock()


def _load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(lid, entry):
    with _lock:
        cache = _load(CACHE)
        cache[lid] = entry
        CACHE.write_text(json.dumps(cache, indent=1))


# ---------------- one lender through the tiers ----------------
def resolve(lender, anchor, now=None) -> dict:
    lid, name, ltype, (pkind, purl), backup = lender
    now = now or datetime.now(timezone.utc)
    tried = []

    def attempt(tier, fn, url_for_row):
        try:
            rows, note = fn()
        except Exception as e:                                  # network error, blocked, bad JSON...
            tried.append({"tier": tier, "ok": False, "reason": f"{type(e).__name__}"})
            return None
        if not rows:
            tried.append({"tier": tier, "ok": False, "reason": note or "no rates found"})
            return None
        ok, why = validate(rows, ltype, anchor)
        tried.append({"tier": tier, "ok": ok, "reason": why if not ok else (note or "ok")})
        return (rows, url_for_row, note) if ok else None

    got = attempt("primary", lambda: (read_live(pkind, purl), None), purl)
    tier = "primary"
    if not got:
        tier = "backup1"
        if backup:
            got = attempt("backup1", lambda: (read_live(backup[0], backup[1]), "second live source"), backup[1])
        else:
            got = attempt("backup1", lambda: _with_note(read_rediscovered(purl), "rediscovered"), purl)
    if got:
        rows, url, note = got
        as_of = now.isoformat(timespec="seconds")
        _save_cache(lid, {"at": as_of, "tier": tier, "url": url, "rows": rows})
        history.save(lid, now.date().isoformat(), rows, "api" if pkind.endswith("_api") and tier == "primary" else "html")
        return _row(lender, tier, as_of, url, rows, tried, anchor)
    entry = _load(CACHE).get(lid)
    if entry and datetime.fromisoformat(entry["at"]) >= now - timedelta(days=CACHE_DAYS):
        ok, why = validate(entry["rows"], ltype, anchor)
        tried.append({"tier": "cache", "ok": ok, "reason": why if not ok else f"saved {entry['at']}"})
        if ok:
            return _row(lender, "cache", entry["at"], entry["url"], entry["rows"], tried, anchor)
    else:
        tried.append({"tier": "cache", "ok": False, "reason": "no reading in the last %d days" % CACHE_DAYS})
    got = attempt("archive", lambda: read_archive(backup[0] if (backup and pkind == "td_api") else pkind,
                                                  backup[1] if (backup and pkind == "td_api") else purl), purl)
    if got:
        rows, url, note = got
        return _row(lender, "archive", note, url, rows, tried, anchor)
    if ltype == "bank" and anchor.get("boc_5y_posted") is not None:
        rows = [(60, "fixed_closed", "posted", anchor["boc_5y_posted"])]
        return _row(lender, "boc_typical", anchor.get("boc_5y_posted_date"),
                    "https://www.bankofcanada.ca/rates/banking-and-financial-statistics/posted-interest-rates-offered-by-chartered-banks/",
                    rows, tried, anchor)
    return _row(lender, "unavailable", None, purl, [], tried, anchor)


def _with_note(pair, note):
    rows, url = pair
    return rows, (f"{note}: {url}" if url else None)


def _row(lender, tier, as_of, url, rows, tried, anchor):
    lid, name, ltype, *_ = lender
    terms = summarize(rows)
    five = terms.get(60, {})
    return {"id": lid, "name": name, "type": ltype, "tier": tier, "tier_label": TIER_LABEL[tier], "as_of": as_of,
            "source_url": url, "rates": {str(t): v for t, v in sorted(terms.items())},
            "five_year": {"posted": five.get("posted"), "special": five.get("special"),
                          "advertised": min(five.values()) if five else None},
            "lender_specific": tier not in ("boc_typical", "unavailable"), "tried": tried}


# ---------------- board ----------------
_refresh_lock = threading.Lock()
REFRESH_LOCK = DATA / "live_refresh.lock"


def refresh(lenders=None) -> dict:
    """One collection at a time: a concurrent call waits for the running one and returns its board."""
    import os
    if not _refresh_lock.acquire(blocking=False):
        with _refresh_lock:                                   # wait for the in-flight refresh, then reuse it
            return _load(BOARD)
    try:
        try:
            fd = os.open(REFRESH_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = datetime.now().timestamp() - REFRESH_LOCK.stat().st_mtime
            if age < 600:                                     # another process is collecting
                return _load(BOARD) or {"refreshed_at": None, "banks": [], "credit_unions": [], "busy": True}
            REFRESH_LOCK.unlink(missing_ok=True)              # stale lock from a crash
            fd = os.open(REFRESH_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        try:
            return _refresh(lenders)
        finally:
            REFRESH_LOCK.unlink(missing_ok=True)
    finally:
        _refresh_lock.release()


def _refresh(lenders=None) -> dict:
    anchor = market_anchor()
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(lambda l: resolve(l, anchor, now), lenders or LENDERS))
    board = {"refreshed_at": now.isoformat(timespec="seconds"), "anchor": anchor,
             "summary": {t: sum(1 for r in rows if r["tier"] == t) for t in TIER_LABEL},
             "banks": [r for r in rows if r["type"] == "bank"],
             "credit_unions": [r for r in rows if r["type"] == "credit_union"]}
    BOARD.write_text(json.dumps(board, indent=1))
    return board


_refreshing = threading.Event()


def board(max_age=STALE_AFTER) -> dict:
    """Last board; kicks off a background refresh when stale. Never blocks on the network if a board exists."""
    b = _load(BOARD)
    stale = not b or datetime.fromisoformat(b["refreshed_at"]) < datetime.now(timezone.utc) - max_age
    if not b:
        return refresh()
    if stale and not _refreshing.is_set():
        _refreshing.set()

        def run():
            try:
                refresh()
            finally:
                _refreshing.clear()
        threading.Thread(target=run, daemon=True).start()
    return {**b, "stale": stale, "refreshing": _refreshing.is_set()}


if __name__ == "__main__":
    b = refresh()
    print(f"refreshed {b['refreshed_at']}  anchor {b['anchor']}")
    for group in ("banks", "credit_unions"):
        print(f"\n{group}")
        for r in b[group]:
            f = r["five_year"]
            print(f"  {r['name']:22} {r['tier_label']:30} 5y posted={f['posted']} special={f['special']} "
                  f"advertised={f['advertised']}  ({r['as_of']})")
```

## Lender feed readers used by the board (TD, CIBC, Scotiabank, BMO, Simplii) and archive helpers
`backend/renewal/ratewatch/scrape.py` (347 lines)

```python
"""Fetch today's rate table for each source. Hidden-API fetchers first (exact), generic HTML parser second.

Every fetcher returns rows: (term_months, kind, rate_type, rate)
  kind:      fixed_closed | variable | open
  rate_type: posted | special | discount | special_insured
If a fetcher breaks: see FIX notes beside it, then run  python -m renewal.ratewatch.scrape P023  to test one source.
"""
from .paths import DATA as _DATA
import codecs, json, re, sys
from pathlib import Path
import requests
from .linkcheck import UA
from .parse import extract_rates
from .registry import PRIMARY

def _get(url, **kw):
    return requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=kw.pop("timeout", 30), **kw)


def td():
    """TD hides rates behind a POST. Config is embedded in the page as window.ratesAPIInfo.
    Response per product key, e.g. MTGF060C = MorTGage Fixed 060 months Closed:
        [posted, discount, special, APR, flag]  (nonHighRatio = conventional)
    FIX: if 405/empty -> reload page, re-read ratesAPIInfo (url/params may change);
         if keys change -> open the page in a browser, DevTools > Network > filter 'getRates'."""
    page = _get("https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates").text
    raw = re.search(r'ratesAPIInfo\s*=\s*(["\'])(.*?)\1\s*;', page, re.S).group(2)
    info = json.loads(codecs.decode(raw.replace("\\/", "/"), "unicode_escape"))
    rows = []
    for src in info["rates"]:
        if len(src["urls"]) != 1:
            continue
        body = {"akaNames": src["productNames"]} if src.get("productNames") else {p["key"]: p["value"] for p in src.get("additionalParams", [])}
        data = requests.post(src["urls"][0], json=body, headers={**UA, "Origin": "https://www.td.com", "Referer": "https://www.td.com/"}, timeout=30).json()
        for key, v in data.items():
            m = re.match(r"(MTG|FLT)([FV])(\d{3})([CO])", key)
            if not m or m.group(1) != "MTG":
                continue
            term = int(m.group(3))
            kind = "open" if m.group(4) == "O" else ("variable" if m.group(2) == "V" else "fixed_closed")
            vals = v.get("nonHighRatio") or v.get("highRatio")
            posted, disc, special = (float(x) for x in vals[:3])
            rows += [(term, kind, "posted", posted), (term, kind, "discount", disc), (term, kind, "special", special)]
            hr = v.get("highRatio")
            if hr:
                rows.append((term, kind, "special_insured", float(hr[2])))
    return rows


def cibc():
    """CIBC serves JS variables (not JSON) from cibconline. Per product (FRCM = Fixed Rate Closed Mortgage):
        ['5_null_null_Years_T', null, TYPE, 'rate', ...]   TYPE 1=posted 18=special 2=APR 34=insured special (unverified)
    FIX: open the rates page in a browser, DevTools > Network > filter 'productRates' to get new codes."""
    url = ("https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5&sourceProductCode="
           "FRCM%2c5YRVARCLO%2cFOM%2cVROM%2c")
    return cibc_rows(_get(url, headers={"Origin": "https://www.cibc.com", "Referer": "https://www.cibc.com/"}).text)


def cibc_rows(t):
    """Parse CIBC's productRatesLegacy JS-variable response (live or archived)."""
    kinds = {"FRCM": "fixed_closed", "5YRVARCLO": "variable", "FOM": "open", "VROM": "open"}
    types = {1: "posted", 18: "special", 34: "special_insured"}
    rows = []
    for var, body in re.findall(r"var (\w+) = \{(.*?)\]\}", t, re.S):
        if var.lstrip("p") not in kinds:
            continue
        for n, unit, typ, val in re.findall(r"\['(\d+)_null_null_(Years?|Months?)_T', null, (\d+), '([-\d.]+)'", body):
            v, typ = float(val), int(typ)
            if v < 0 or typ not in types:
                continue
            term = int(n) * (12 if unit.startswith("Y") else 1)
            rows.append((term, kinds[var.lstrip("p")], types[typ], v))
    return rows


def scotia():
    """Scotiabank: JSON API named in its own bundle (bns.dynamic-tokens.*.js -> mortgageRates.standard.url).
    nonspecialmortgage = posted rates per product; 'CONVENTIONAL RESIDENTIAL' is the conventional row.
    FIX: re-read mortgageRates in https://www.scotiabank.com/etc.clientlibs/scotiabank/clientlibs/bns.dynamic-tokens*.js"""
    h = {"Origin": "https://www.scotiabank.com", "Referer": "https://www.scotiabank.com/"}
    return scotia_rows(_get("https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage", headers=h).json())


def scotia_rows(js):
    rows = []
    for prod in js.get("data", []):
        name = prod.get("PRODUCT", "").upper()
        if "CONVENTIONAL" not in name and "N.H.A" not in name:
            continue
        rtype = "posted" if "CONVENTIONAL" in name else "posted_insured"
        for t in prod.get("TERMS", []):
            term = int(t["TERM_VALUE"]) * (12 if t["TERM_UNIT"].upper().startswith("Y") else 1)
            rows.append((term, "fixed_closed", rtype, float(t["RATE"])))
    return rows


def simplii():
    """Simplii (CIBC subsidiary): posted from online.simplii.com v2 'rates/ALL' (rateType fixed_rate),
    specials are CIBC's productRatesLegacy type 18 (same feed the Simplii page calls).
    FIX: DevTools on simplii.com/en/rates/mortgage-rates.html, filter 'ebm-pno'."""
    data = _get("https://online.simplii.com/ebm-pno/api/v2/json/rates/ALL",
                headers={"Origin": "https://www.simplii.com", "Referer": "https://www.simplii.com/"}).json()
    rows = []
    for x in data:
        if x.get("rateProductCategory") != "MORTGAGE" or x.get("mortgageType") != "fixed_rate" or x.get("rateType") != "fixed_rate":
            continue
        t = x["term"]
        term = int(t["value"]) * (12 if t["type"] == "year" else 1)
        rows.append((term, "fixed_closed", "posted", float(x["interestRates"][0]["rateValue"])))
    rows += [r for r in cibc() if r[2] == "special"]
    return rows


def bmo_posted_rows(js):
    rows = []
    for item in js.get("mortgageRates", {}).get("fixed", {}).values():
        label = item.get("en", "").lower()
        if "convertible" in label:
            continue
        rows.append((int(item["term_months"]), "open" if "open" in label else "fixed_closed", "posted", float(item["value"])))
    return rows


def bmo():
    """BMO: public JSON. epm/v1.0/bmo-epm-mortgage.json = posted by term; v2.0/bmo-ca-mortgages-rates.json = specials.
    bmo.com often drops scripted connections, so on failure fall back to the newest Wayback copy of the same JSON.
    FIX: DevTools on bmo.com mortgage-rates page, filter 'public-data'."""
    base = "https://www.bmo.com/public-data/api"
    def load(path):
        try:
            return _get(f"{base}/{path}", timeout=20).json()
        except Exception:
            r = _get_retry(f"https://web.archive.org/web/2id_/{base}/{path}", timeout=60)   # 2id_ = newest raw snapshot
            return r.json() if r is not None and r.ok else {}
    rows = bmo_posted_rows(load("epm/v1.0/bmo-epm-mortgage.json"))
    for key, val in load("v2.0/bmo-ca-mortgages-rates.json").items():
        m = re.match(r"(?:smart)?[Ff]ixed(\d+)YearClosedSpecial$", key) or re.match(r"smartFixed(\d+)YearClosedSpecial$", key)
        if m and isinstance(val, (int, float)):
            rows.append((int(m.group(1)) * 12, "fixed_closed", "special", float(val)))
        elif key == "smartFixed5YearClosedHighRatioSpecial":
            rows.append((60, "fixed_closed", "special_insured", float(val)))
    return rows


FETCHERS = {"P023": td, "P029": cibc, "P025": scotia, "P034": simplii, "P027": bmo}


def _dedupe(rows):
    seen, out = set(), []
    for r in rows:
        if r[:3] not in seen:
            seen.add(r[:3])
            out.append(r)
    return out


def fetch(source_id):
    row = next(r for r in PRIMARY if r[0] == source_id)
    if source_id in FETCHERS:
        return _dedupe(FETCHERS[source_id]()), "api"
    html = _get(row[4]).text
    return extract_rates(html, source_id), "html"


# ---------------- Two automatic replacements per source + triple check ----------------
def _get_retry(url, tries=3, **kw):
    """Archives rate-limit (HTTP 429/503). Back off 5s, 15s, 45s before giving up."""
    import time
    time.sleep(1.5)                     # archives are shared public services - stay polite or get blocked
    for i in range(tries):
        try:
            r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=kw.pop("timeout", 60), **kw)
            if r.status_code not in (429, 503):
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * 3 ** i)
    return None


def wayback_latest(url, max_age_days=14):
    """Backup 2: the Internet Archive's newest copy of the same page (availability API, CDX fallback)."""
    from datetime import datetime, date
    ts = None
    r = _get_retry("https://archive.org/wayback/available", params={"url": url})
    try:
        ts = r.json()["archived_snapshots"]["closest"]["timestamp"]
    except Exception:
        r = _get_retry("https://web.archive.org/cdx/search/cdx", params={
            "url": url.split("://", 1)[1], "output": "json", "filter": "statuscode:200", "limit": -1, "fl": "timestamp"})
        try:
            ts = r.json()[-1][0]
        except Exception:
            return [], None
    if (date.today() - datetime.strptime(ts[:8], "%Y%m%d").date()).days > max_age_days:
        return [], ts
    r = _get_retry(f"https://web.archive.org/web/{ts}id_/{url}", timeout=90)
    return (extract_rates(r.text) if r is not None and r.ok else []), ts


BAD_PAGE = re.compile(r"gic|resp|rdsp|rrsp|tfsa|savings|deposit|chequing|blog|news|forecast|article|insight|"
                      r"investment-corp|global-customer|credit-card|/fr/|newfoundland|quebec", re.I)


def plausible(rows, goc5=None):
    """Acceptance test for any replacement page: must hold a 5yr fixed rate in a sane band."""
    five = [r for t, k, rt, r in rows if t == 60 and k == "fixed_closed" and not rt.endswith("_insured")]
    if not five:
        return False
    if goc5 is None:
        try:
            goc5 = float(requests.get("https://www.bankofcanada.ca/valet/observations/BD.CDN.5YR.DQ.YLD/json?recent=1",
                                      timeout=30).json()["observations"][-1]["BD.CDN.5YR.DQ.YLD"]["v"])
        except Exception:
            goc5 = 3.0
    return all(goc5 + 0.3 <= r <= goc5 + 5.0 for r in five)


def rediscovered(url):
    """Backup 1: crawl the lender's own sitemap for the page's new address. A candidate is only accepted if
    it is a mortgage page (not GIC/RESP/blog...) AND passes plausible(). Otherwise nothing is saved."""
    from urllib.parse import urlparse
    from .discover import discover
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for _, cand in discover(base, ("rates",), use_wayback=False)[:6]:
        if cand.rstrip("/") == url.rstrip("/") or BAD_PAGE.search(cand):
            continue
        try:
            html = _get(cand).text
        except requests.RequestException:
            continue
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        if "mortgage" not in cand.lower() and not (title and "mortgage" in title.group(1).lower()):
            continue
        rows = extract_rates(html)
        if rows and plausible(rows):
            return rows, cand
    return [], None


def commoncrawl_latest(url, max_age_days=60):
    """Backup #3: Common Crawl (a second, independent web archive). Reads one WARC record by byte range."""
    import gzip, io
    from datetime import date, datetime
    try:
        recs = []
        for crawl in requests.get("https://index.commoncrawl.org/collinfo.json", timeout=30).json()[:3]:
            r = _get_retry(crawl["cdx-api"], params={"url": url, "output": "json"}, timeout=60)
            if r is not None and r.ok:
                recs = [x for x in r.text.strip().splitlines() if '"status": "200"' in x]
                if recs:
                    break
        if not recs:
            return [], None
        rec = json.loads(recs[-1])
        if (date.today() - datetime.strptime(rec["timestamp"][:8], "%Y%m%d").date()).days > max_age_days:
            return [], rec["timestamp"]
        start, length = int(rec["offset"]), int(rec["length"])
        raw = requests.get(f"https://data.commoncrawl.org/{rec['filename']}", timeout=90,
                           headers={"Range": f"bytes={start}-{start + length - 1}"}).content
        warc = gzip.GzipFile(fileobj=io.BytesIO(raw)).read().decode("utf-8", "replace")
        html = warc.split("\r\n\r\n", 2)[-1]
        return extract_rates(html), rec["timestamp"]
    except Exception:
        return [], None


# ---- auto-fix memory: a working replacement URL found by rediscovery is saved and used from then on ----
OVERRIDES = _DATA / "url_overrides.json"
FIXLOG = _DATA / "fixes.log"


def _overrides():
    try:
        return json.loads(OVERRIDES.read_text())
    except (OSError, ValueError):
        return {}


def _remember_fix(source_id, old, new):
    o = _overrides()
    o[source_id] = new
    OVERRIDES.parent.mkdir(exist_ok=True)
    OVERRIDES.write_text(json.dumps(o, indent=2))
    from datetime import datetime
    with open(FIXLOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {source_id} AUTO-FIXED {old} -> {new}\n")


def fetch_confirmed(source_id, tol=0.01):
    """Primary + 3 backups, repaired automatically:
         primary      the registry URL / hidden API (or a saved auto-fix URL)
         backup 1     rediscovery on the lender's own sitemap -> if it works, URL is saved (auto-fix)
         backup 2     Wayback Machine newest snapshot (<=14 days old)
         backup 3     Common Crawl newest capture (<=60 days old)
       Every value gets a status:
         CONFIRMED  two independent reads agree within `tol`
         SINGLE     only one read had it (usable, flagged unconfirmed)
         CONFLICT   reads disagree -> the penalty engine will not call a result accurate
       Returns (rows_with_status, log)."""
    row = next(r for r in PRIMARY if r[0] == source_id)
    url = _overrides().get(source_id, row[4])
    log = []
    try:
        primary, how = fetch(source_id) if url == row[4] else (extract_rates(_get(url).text, source_id), "html (auto-fixed URL)")
    except Exception as e:
        primary, how = [], f"error {type(e).__name__}"
    log.append(f"primary {how}: {len(primary)} values")
    if not primary:
        found, new = rediscovered(url)
        log.append(f"backup 1 rediscover {new}: {len(found)} values")
        if found:
            _remember_fix(source_id, url, new)
            log.append("   AUTO-FIXED: new URL saved to data/url_overrides.json")
            primary, url = found, new
    alt, ts = wayback_latest(url)
    log.append(f"backup 2 wayback {ts}: {len(alt)} values")
    if not alt or not primary:
        cc, cts = commoncrawl_latest(url)
        log.append(f"backup 3 common crawl {cts}: {len(cc)} values")
        if not alt:
            alt = cc
        elif not primary:
            primary = cc
    base = {r[:3]: r[3] for r in primary} or {r[:3]: r[3] for r in alt}
    other = {r[:3]: r[3] for r in alt} if primary else {}
    out = []
    for k, v in base.items():
        if k in other:
            status = "CONFIRMED" if abs(other[k] - v) <= tol else "CONFLICT"
        else:
            status = "SINGLE"
        out.append((*k, v, status))
    return out, log


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    for sid in [a for a in sys.argv[1:] if not a.startswith("--")]:
        if confirm:
            rows, log = fetch_confirmed(sid)
            print(sid, *log, sep="\n  ")
        else:
            rows, how = fetch(sid)
            print(sid, how, len(rows))
        for r in sorted(rows):
            print("   ", r)
```

## Page parser (English/French, posted vs special columns)
`backend/renewal/ratewatch/parse.py` (226 lines)

```python
"""Turn any lender rate page into rows: (term_months, kind, rate_type, rate).

Works on raw HTML (requests), Wayback snapshots, or browser-rendered HTML. Generic first; add a
per-source override in OVERRIDES when a lender's layout defeats the heuristic (fix it here, nowhere else).
"""
import json, re
from bs4 import BeautifulSoup

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10}
# English and French terms: "5 year", "5-yr", "6 month", "5 ans", "1 an", "6 mois"
TERM_RE = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|ten)\s*[- ]?\s*(year|yr|month|mo|ans?|mois)s?\b", re.I)
# "6.19%", "6,19 %", "6,190 %" (French uses a comma and a (non-breaking) space before %)
PCT_RE = re.compile(r"(\d{1,2}[.,]\d{2,3})\s?%")


POSTED_WORDS = ("posted", "affiché", "affiche")
SPECIAL_WORDS = ("special", "spécial", "offer", "offre", "promotion", "discount", "réduit", "our rate")
APR_WORDS = ("apr", "tap", "taux annuel")


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _term_months(n, unit):
    n = WORDNUM.get(n.lower(), None) or int(n)
    return n if unit.lower().startswith("mo") else n * 12


def _kind(label):
    l = label.lower()
    if "variable" in l or "adjustable" in l:
        return "variable"
    if re.search(r"\bopen\b|\bouvert", l):
        return "open"
    return "fixed_closed"


def _table_type(table):
    """Read the column header + nearest heading: 'Posted Rates' vs 'Special Offers', and whether an APR column exists."""
    head = table.find("tr")
    heading = table.find_previous(["h2", "h3", "h4", "caption"])
    ctx = ((head.get_text(" ", strip=True) if head else "") + " " + (heading.get_text(" ", strip=True) if heading else "")).lower()
    rtype = "posted" if any(w in ctx for w in POSTED_WORDS) else "special" if any(w in ctx for w in SPECIAL_WORDS) else None
    return rtype, "apr" in ctx


def _column_types(table):
    """Header cells -> rate type per column: 'posted', 'special', 'apr' or None. Uses the first row with header text."""
    head = table.find("tr")
    if not head:
        return []
    out = []
    for cell in head.find_all(["th", "td"]):
        span = int(cell.get("colspan", 1) or 1)
        t = cell.get_text(" ", strip=True).lower()
        kind = "apr" if any(w in t.split() or w in t for w in APR_WORDS) else "posted" if any(w in t for w in POSTED_WORDS) else             "special" if any(w in t for w in SPECIAL_WORDS + ("best",)) else None
        out += [kind] * span
    return out


def _rows_by_column(table, cols):
    """When a table has separate Posted / Special columns, read each value from its own column."""
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(" ", strip=True)
        m = TERM_RE.search(label)
        if not m:
            continue
        term = _term_months(m.group(1), m.group(2))
        if term not in (6, 12, 24, 36, 48, 60, 72, 84, 120):
            continue
        kind = _kind(label)
        insured = bool(re.search(r"high[- ]?ratio|insured", label, re.I))
        for j, cell in enumerate(cells[1:], start=1):
            ctype = cols[j] if j < len(cols) else None
            if ctype not in ("posted", "special"):
                continue
            txt = cell.get_text(" ", strip=True)
            br = re.search(r"\((\d{1,2}[.,]\d{2,3})\s?%\)", txt)
            pct = PCT_RE.search(txt) if not br else br
            if pct:
                v = _f(pct.group(1))
                if 0.5 <= v <= 15:
                    rows.append((term, kind, ctype + ("_insured" if insured else ""), v))
    return rows


def _rows_from_segment(seg, forced_type=None, has_apr=False):
    if forced_type:
        m = TERM_RE.search(seg)
        pcts = [_f(x) for x in PCT_RE.findall(seg)]
        if not m or not pcts:
            return []
        term = _term_months(m.group(1), m.group(2))
        if term not in (6, 12, 24, 36, 48, 60, 72, 84, 120):
            return []
        if "prime" in seg.lower():          # variable: "Prime - 0.300 % (4.150%)" -> take the bracketed effective rate
            br = re.search(r"\((\d{1,2}[.,]\d{2,3})\s?%\)", seg)
            if not br:
                return []
            pcts = [_f(br.group(1))]
        return [(term, _kind(seg[:120]), forced_type, pcts[0])]
    out = []
    m = TERM_RE.search(seg)
    if not m:
        return out
    term = _term_months(m.group(1), m.group(2))
    if term not in (6, 12, 24, 36, 48, 60, 72, 84, 120):
        return out
    pcts = [_f(x) for x in PCT_RE.findall(seg[m.start():m.start() + 260])]
    pcts = [p for p in pcts if 0.5 <= p <= 15]
    if not pcts:
        return out
    # drop APR shadows (an APR sits within ~0.06 of its rate)
    clean = [pcts[0]] + [p for prev, p in zip(pcts, pcts[1:]) if abs(p - prev) > 0.06]
    kind = _kind(seg[:120])
    if len(clean) >= 2:
        out.append((term, kind, "posted", max(clean[:2])))
        out.append((term, kind, "special", min(clean[:2])))
    else:
        label = seg.lower()
        out.append((term, kind, "special" if any(w in label for w in SPECIAL_WORDS + ("best",)) else "posted", clean[0]))
    return out


def _from_json_blobs(soup):
    """Many bank pages embed their rate table as JSON (__NEXT_DATA__, data-rates, window.__STATE__)."""
    rows = []
    for sc in soup.find_all("script"):
        txt = sc.string or ""
        if "rate" not in txt.lower() or len(txt) > 3_000_000:
            continue
        for m in re.finditer(r'\{[^{}]*?(?:"term"|"termLength"|"term_months")[^{}]*?\}', txt):
            try:
                d = json.loads(m.group(0))
            except ValueError:
                continue
            rate = d.get("rate") or d.get("postedRate") or d.get("value")
            try:
                if d.get("term_months") is not None:                     # explicit months: never rescale
                    months = int(float(d["term_months"]))
                else:
                    raw = str(d.get("term") or d.get("termLength") or "").strip()
                    tm = TERM_RE.search(raw)
                    if tm:
                        months = _term_months(tm.group(1), tm.group(2))
                    elif re.fullmatch(r"\d+(\.\d+)?", raw):
                        n = float(raw)                                    # bare number: <=10 means years
                        months = int(round(n * 12)) if n <= 10 else int(n)
                    else:
                        continue
                if rate and months in (6, 12, 24, 36, 48, 60, 72, 84, 120):
                    label = json.dumps(d).lower()
                    rows.append((months, _kind(label), "posted" if "posted" in label else "special", float(str(rate).strip("%"))))
            except (ValueError, TypeError):
                pass
    return rows


def extract_rates(html, source_id=None):
    if source_id in OVERRIDES:
        return OVERRIDES[source_id](html)
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.find_all("table"):
        cols = _column_types(table)
        if "posted" in cols and "special" in cols:            # both kinds in one table: read column by column
            rows += _rows_by_column(table, cols)
            continue
        rtype, apr = _table_type(table)
        for tr in table.find_all("tr")[1:] if rtype else table.find_all("tr"):
            text = tr.get_text(" ", strip=True)
            got = _rows_from_segment(text, rtype, apr)
            if re.search(r"high[- ]?ratio|insured", text, re.I):     # keep insured pricing out of conventional
                got = [(t, k, rt + "_insured", r) for t, k, rt, r in got]
            rows += got
    if not rows:
        for el in soup.select("li, .rate, [class*=rate], [class*=Rate], div"):
            t = el.get_text(" ", strip=True)
            if 8 < len(t) < 300 and PCT_RE.search(t):
                rows += _rows_from_segment(t)
    if not rows:
        rows = _from_json_blobs(soup)
    # de-dupe: keep first occurrence of each (term, kind, type)
    seen, out = set(), []
    for r in rows:
        k = r[:3]
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ---- Per-source overrides: add a function when the generic parser gets a page wrong ----
def _atb(html):
    """ATB: page has a 'Client Rates' section (discounted) then a 'Posted Rates' section with the SAME table
    names. Section = nearest preceding 'Posted Rates' / 'Client Rates' label. Rows say 'conventional' or
    'high ratio'; un-labelled rows are conventional. Rate First (a no-frills product) is kept separate."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for t in soup.find_all("table"):
        sec = t.find_previous(string=re.compile(r"^\s*(Posted|Client) Rates\s*$"))
        heading = (t.find_previous(["h2", "h3", "h4", "caption"]) or t).get_text(" ", strip=True).lower()
        if not sec or "our featured" in heading:
            continue
        rtype = "posted" if sec.strip().lower().startswith("posted") else "special"
        if "rate first" in heading:
            rtype += "_ratefirst"
        for tr in t.find_all("tr"):
            text = tr.get_text(" ", strip=True)
            got = _rows_from_segment(text, rtype)
            if re.search(r"high[- ]?ratio", text, re.I):
                got = [(a, k, rt + "_insured", r) for a, k, rt, r in got]
            if "open" in heading:
                got = [(a, "open", rt, r) for a, k, rt, r in got]
            elif "variable" in heading:
                got = [(a, "variable", rt, r) for a, k, rt, r in got]
            rows += got
    return rows


OVERRIDES = {"P039": _atb}
```

## Rate history store (last-good readings, conflicts)
`backend/renewal/ratewatch/history.py` (122 lines)

```python
"""Rate history database (SQLite, data/rates.db). The posted rate on the ORIGINATION date is the #1 IRD input.

Three ways rows get in:
  snapshot()        today's scrape of every source (run daily - this is how you build years of history)
  official()        Bank of Canada posted (big-6 typical), prime, bond yields - back to the 1950s for posted rates
  backfill(id, y)   Wayback Machine snapshots of a lender's own rate page, one per month since year y
"""
from .paths import DATA as _DATA
import sqlite3, time
from datetime import date, datetime
from pathlib import Path
import requests
from .linkcheck import UA
from .parse import extract_rates
from .registry import PRIMARY

DB = _DATA / "rates.db"
SCHEMA = """CREATE TABLE IF NOT EXISTS rates(
  source TEXT, day TEXT, term INTEGER, kind TEXT, rtype TEXT, rate REAL, how TEXT,
  PRIMARY KEY(source, day, term, kind, rtype, how))"""


def db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute(SCHEMA)
    return c


def save(source, day, rows, how):
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO rates VALUES (?,?,?,?,?,?,?)",
                      [(source, day, t, k, rt, r, how) for t, k, rt, r in rows])


def table_on(source, day, rtype="posted", kind="fixed_closed", max_age_days=45):
    """Lender's {term: rate} in force on `day` = latest snapshot on or before that day."""
    with db() as c:
        row = c.execute("SELECT MAX(day) FROM rates WHERE source=? AND day<=? AND rtype=? AND kind=?",
                        (source, str(day), rtype, kind)).fetchone()
        if not row or not row[0]:
            return {}, None
        if (date.fromisoformat(str(day)) - date.fromisoformat(row[0])).days > max_age_days:
            return {}, row[0]
        rs = c.execute("SELECT term, rate, how FROM rates WHERE source=? AND day=? AND rtype=? AND kind=?",
                       (source, row[0], rtype, kind)).fetchall()
        # One capture per answer: never mix a live feed with an archive copy taken the same day.
        best = min({how for _, _, how in rs}, key=lambda h: HOW_PRIORITY.get(h, 9))
        return {t: r for t, r, how in rs if how == best}, row[0]


HOW_PRIORITY = {"api": 0, "html": 1, "wayback": 2, "commoncrawl": 3, "boc": 4}


def conflicts(source=None, since=None, tol=0.005):
    """Same lender, same day, same term/type, different rates from different collection methods.
    These are reported (validate.py rule R9, dataset.py rate_conflicts.csv), never silently merged."""
    q = ("SELECT a.source, a.day, a.term, a.kind, a.rtype, a.how, a.rate, b.how, b.rate FROM rates a JOIN rates b "
         "ON a.source=b.source AND a.day=b.day AND a.term=b.term AND a.kind=b.kind AND a.rtype=b.rtype AND a.how<b.how "
         "WHERE ABS(a.rate-b.rate) > ?")
    args = [tol]
    if source:
        q += " AND a.source=?"
        args.append(source)
    if since:
        q += " AND a.day>=?"
        args.append(str(since))
    with db() as c:
        return c.execute(q, args).fetchall()


# ---------------- Bank of Canada (official, exact, decades deep) ----------------
VALET = "https://www.bankofcanada.ca/valet/observations"
BOC_SERIES = {"V80691333": (12, "posted"), "V80691334": (36, "posted"), "V80691335": (60, "posted")}


def official(start="2000-01-01"):
    """BIG6_TYPICAL = BoC 'conventional mortgage' series = the most common big-6 posted rate each week."""
    js = requests.get(f"{VALET}/group/CHARTERED_BANK_INTEREST/json", params={"start_date": start}, timeout=60).json()
    by_day = {}
    for ob in js["observations"]:
        for sid, (term, rt) in BOC_SERIES.items():
            if sid in ob and ob[sid].get("v"):
                by_day.setdefault(ob["d"], []).append((term, "fixed_closed", rt, float(ob[sid]["v"])))
        if "V80691311" in ob and ob["V80691311"].get("v"):
            by_day.setdefault(ob["d"], []).append((0, "prime", "posted", float(ob["V80691311"]["v"])))
    for d, rows in by_day.items():
        save("BIG6_TYPICAL", d, rows, "boc")
    js = requests.get(f"{VALET}/group/bond_yields_benchmark/json", params={"start_date": start}, timeout=60).json()
    terms = {"2YR": 24, "3YR": 36, "5YR": 60, "7YR": 84, "10YR": 120}
    by_day = {}
    for ob in js["observations"]:
        for k, v in ob.items():
            for tag, term in terms.items():
                if f".{tag}." in k and v.get("v"):
                    by_day.setdefault(ob["d"], []).append((term, "bond", "yield", float(v["v"])))
    for d, rows in by_day.items():
        save("GOC", d, rows, "boc")
    return len(by_day)


# ---------------- Wayback backfill (lender's own page, historical) ----------------
def backfill(source_id, from_year=2019, per="month", pause=1.5):
    """One snapshot per month (or per day with per='day'). id_ in the URL returns the original HTML untouched.
    FIX: if a period has no rows, the page layout differed then - add a dated rule in parse.OVERRIDES."""
    url = next(r[4] for r in PRIMARY if r[0] == source_id)
    collapse = "timestamp:6" if per == "month" else "timestamp:8"
    cdx = requests.get("https://web.archive.org/cdx/search/cdx", headers=UA, timeout=90, params={
        "url": url.split("://", 1)[1], "output": "json", "from": str(from_year), "filter": "statuscode:200",
        "collapse": collapse, "fl": "timestamp,original"}).json()
    got = 0
    for ts, orig in cdx[1:]:
        try:
            html = requests.get(f"https://web.archive.org/web/{ts}id_/{orig}", headers=UA, timeout=60).text
        except requests.RequestException:
            continue
        rows = extract_rates(html, source_id)
        if rows:
            save(source_id, datetime.strptime(ts[:8], "%Y%m%d").date().isoformat(), rows, "wayback")
            got += 1
        time.sleep(pause)
    return got, len(cdx) - 1
```

## Moved-page rediscovery (Backup 1 fallback)
`backend/renewal/ratewatch/discover.py` (113 lines)

```python
"""Self-healing URL finder. When a lender moves its rate page, find the new one.

    python -m renewal.ratewatch.discover P025            # one registry id
    python -m renewal.ratewatch.discover https://www.scotiabank.com rates   # any site + keyword set

Order of attack (cheapest first):
  1. robots.txt -> every Sitemap: line -> sitemap index -> child sitemaps
  2. /sitemap.xml, /sitemap_index.xml, /en/sitemap.xml guesses
  3. homepage links (anchor text + href)
  4. Wayback CDX prefix search (finds URLs the site used to have, newest first)
Scores each candidate URL by keyword hits and prints the top 15.
"""
import re, sys
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from .linkcheck import UA
from .registry import PRIMARY, CHECKS

KEYWORDS = {
    "rates": ["mortgage-rate", "mortgage_rate", "mortgagerate", "rates/mortgage", "mortgages/rates", "/rates", "posted", "taux-hypothecaire"],
    "historical": ["historical", "history", "past-rates", "archive"],
    "penalty": ["prepayment", "penalty", "pre-payment", "charge-calculator", "ird", "break"],
    "prime": ["prime"],
}
BAD = ["/fr/", "-fr", "careers", "blog/", "/news/", ".pdf", "business", "commercial", "wealth", "insurance", "auto", "credit-card"]


def get(url, timeout=20):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        return r.text if r.ok else ""
    except requests.RequestException:
        return ""


def sitemap_urls(base, cap=40):
    seen, queue, found = set(), [], set()
    for line in get(urljoin(base, "/robots.txt")).splitlines():
        if line.lower().startswith("sitemap:"):
            queue.append(line.split(":", 1)[1].strip())
    queue += [urljoin(base, p) for p in ("/sitemap.xml", "/sitemap_index.xml", "/en/sitemap.xml")]
    while queue and len(seen) < cap:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", get(sm)):
            if loc.endswith(".xml") or "sitemap" in loc.lower():
                queue.append(loc)
            else:
                found.add(loc)
    return found


def homepage_links(base):
    soup = BeautifulSoup(get(base), "lxml")
    return {urljoin(base, a["href"]) for a in soup.find_all("a", href=True)}


def wayback_urls(host):
    try:
        r = requests.get("https://web.archive.org/cdx/search/cdx", timeout=40, headers=UA,
                         params={"url": host + "/*", "output": "json", "fl": "original", "collapse": "urlkey",
                                 "filter": ["statuscode:200", "original:.*(rate|prepay|penalt).*"], "limit": 3000})
        return {row[0] for row in r.json()[1:]}
    except Exception:
        return set()


def score(url, kinds):
    u = url.lower()
    s = sum(3 for k in kinds for w in KEYWORDS[k] if w in u)
    s += 1 if "mortgage" in u else 0
    s -= sum(4 for b in BAD if b in u)
    return s


def discover(base, kinds=("rates",), use_wayback=True):
    host = urlparse(base).netloc
    cands = sitemap_urls(base) | homepage_links(base)
    if use_wayback and len([c for c in cands if score(c, kinds) > 2]) < 3:
        cands |= {u if u.startswith("http") else "https://" + u for u in wayback_urls(host)}
    ranked = sorted({c for c in cands if urlparse(c).netloc.endswith(host.replace("www.", ""))}, key=lambda c: -score(c, kinds))
    return [(score(c, kinds), c) for c in ranked[:15] if score(c, kinds) > 0]


def kinds_for(row):
    text = " ".join(map(str, row)).lower()
    if "historical" in text:
        return ("historical", "rates")
    if "calculator" in text or "penalt" in text or "prepay" in text:
        return ("penalty",)
    if "prime" in text and "mortgage" not in text:
        return ("prime",)
    return ("rates",)


def main():
    arg = sys.argv[1]
    if arg.startswith("http"):
        base, kinds = arg, tuple(sys.argv[2:]) or ("rates",)
    else:
        row = next(r for r in PRIMARY + CHECKS if r[0] == arg)
        url = row[4] if len(row) == 8 else row[3]
        base, kinds = f"{urlparse(url).scheme}://{urlparse(url).netloc}", kinds_for(row)
    print(f"# {arg}  {base}  looking for {kinds}")
    for s, u in discover(base, kinds):
        print(f"{s:3}  {u}")


if __name__ == "__main__":
    main()
```

## HTTP API (includes /api/ratewatch/live and /live/refresh)
`backend/renewal/ratewatch/api.py` (229 lines)

```python
"""HTTP endpoints for ratewatch: live lender rates, TD-exact penalty, forecast, backtest report, PDF letter."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
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
    return table, f"history ({seen})"


def _run(body: PenaltyIn):
    payout = body.payout or date.today()
    if body.current_posted:
        table, how = {int(k): v for k, v in body.current_posted.items()}, "supplied"
    elif payout < date.today():
        table, how = _historical_table(body.lender, payout)      # never today's rates for a past date
    else:
        table, how = _live_table(body.lender)
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
    return live.board()


@router.post("/live/refresh")
def live_refresh():
    from . import live
    return live.refresh()
```

## Web page: Live rates
`frontend/js/live-rates.js` (52 lines)

```javascript
/** Live current rates: big banks and credit unions. Data from GET /api/ratewatch/live (primary + 3 backups per lender). */
import {esc, pageHead, button, dt} from './ui.js';

const TIER_CLASS = {primary: 'green-text', backup1: 'green-text', cache: '', archive: '', boc_typical: 'danger-text', unavailable: 'danger-text'};
const pct = v => (v == null ? '—' : `${Number(v).toFixed(2)}%`);

export function ageText(asOf, now = new Date()) {
  if (!asOf) return '';
  const t = Date.parse(asOf);
  if (Number.isNaN(t)) return String(asOf);                       // archive notes like "wayback 20261014"
  const mins = Math.max(0, Math.round((now - t) / 60000));
  if (mins < 60) return `${mins} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} days ago`;
}

function lenderRow(r, banks) {
  const f = r.five_year || {}, rates = r.rates || {};
  const term = m => rates[String(m)] || {};
  const best = m => { const t = term(m); return banks ? t.posted : Math.min(...Object.values(t).filter(v => v != null)); };
  const one = best(12), three = best(36);
  const tried = (r.tried || []).map(t => `${t.tier}: ${t.ok ? 'ok' : t.reason}`).join(' · ');
  return `<tr><td><strong>${esc(r.name)}</strong></td>
    <td>${pct(Number.isFinite(one) ? one : null)}</td><td>${pct(Number.isFinite(three) ? three : null)}</td>
    ${banks ? `<td>${pct(f.posted)}</td><td>${pct(f.special)}</td>` : `<td>${pct(f.advertised)}</td>`}
    <td class="${TIER_CLASS[r.tier] || ''}" title="${esc(tried)}">${esc(r.tier_label)}${r.lender_specific ? '' : ' *'}</td>
    <td>${esc(ageText(r.as_of))}</td>
    <td>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">source</a>` : ''}</td></tr>`;
}

export function liveRatesView(workspace) {
  const b = workspace.liveRates;
  const head = pageHead('LIVE CURRENT RATES', 'Big banks and credit unions',
    'Each lender is read from its own published rates, with three automatic backups if a source fails.',
    button('Refresh now', 'live-rates-refresh', 'dark'));
  if (workspace.liveRatesError) return `${head}<div class="notice warn" role="status">${esc(workspace.liveRatesError)}</div>`;
  if (!b) return `${head}<p>Loading current rates…</p>`;
  const a = b.anchor || {};
  const table = (rows, banks) => `<div class="table-scroll"><table class="compare-table"><thead><tr><th>Lender</th><th>1-yr</th><th>3-yr</th>
      ${banks ? '<th>5-yr posted</th><th>5-yr special</th>' : '<th>5-yr advertised</th>'}<th>Source</th><th>Updated</th><th></th></tr></thead>
      <tbody>${rows.map(r => lenderRow(r, banks)).join('')}</tbody></table></div>`;
  return `${head}
    <div class="notice mb">Refreshed ${esc(ageText(b.refreshed_at))}${b.stale ? ' · refreshing in the background' : ''}.
      Bank of Canada big-six typical 5-year posted: <strong>${pct(a.boc_5y_posted)}</strong>
      ${a.boc_5y_posted_date ? `(${esc(dt(a.boc_5y_posted_date))})` : ''} · 5-year Government of Canada bond: <strong>${pct(a.goc_5y)}</strong></div>
    <section class="card padded"><h3>Big banks</h3>${table(b.banks || [], true)}</section>
    <section class="card padded mt2"><h3>Credit unions</h3>${table(b.credit_unions || [], false)}</section>
    <p class="fineprint mt">Source order per lender: lender feed or page → second lender source (or its moved page, found automatically) →
      last good reading (up to 14 days) → newest web-archive copy. * Not lender-specific: shown only when every lender source fails.
      “Unavailable” means no reading passed validation; no rate is ever estimated. Credit-union “advertised” is the lowest
      5-year fixed rate on the lender’s own page. Hover a source label to see each attempt.</p>`;
}
```

## Backend tests: every tier forced
`tests/test_ratewatch_live.py` (109 lines)

```python
"""Live rates board: every tier, validation, and the API. No network."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import history, live

ANCHOR = {"boc_5y_posted": 6.19, "boc_5y_posted_date": "2026-10-14", "goc_5y": 3.55}
GOOD_BANK = [(60, "fixed_closed", "posted", 6.19), (60, "fixed_closed", "special", 5.14), (36, "fixed_closed", "posted", 6.25)]
GOOD_CU = [(60, "fixed_closed", "posted", 4.84)]
BANK = ("T001", "Test Bank", "bank", ("html", "https://bank.test/rates"), None)
BANK_B1 = ("T002", "Test Bank 2", "bank", ("html", "https://bank2.test/rates"), ("html", "https://bank2.test/fr/taux"))
CU = ("T003", "Test CU", "credit_union", ("html", "https://cu.test/rates"), None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(live, "BOARD", tmp_path / "board.json")
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(live, "read_rediscovered", lambda url: ([], None))
    monkeypatch.setattr(live, "read_archive", lambda kind, url: ([], "no archive copy"))


def boom(*a, **k):
    raise TimeoutError("down")


def test_primary_used_and_cached(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK)
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "primary" and r["five_year"]["posted"] == 6.19 and r["five_year"]["special"] == 5.14
    assert json.loads(live.CACHE.read_text())["T001"]["rows"]


def test_backup1_second_live_source(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK if "/fr/" in url else boom())
    r = live.resolve(BANK_B1, ANCHOR)
    assert r["tier"] == "backup1" and r["source_url"].endswith("/fr/taux")


def test_backup1_rediscovery_when_no_second_source(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: (GOOD_BANK, "https://bank.test/new-rates"))
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "backup1" and any("rediscovered" in t["reason"] for t in r["tried"])


def test_backup2_last_good_reading(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK)
    live.resolve(BANK, ANCHOR)
    monkeypatch.setattr(live, "read_live", boom)
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "cache" and r["five_year"]["posted"] == 6.19


def test_cache_older_than_limit_is_not_used(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=live.CACHE_DAYS + 1)).isoformat()
    live.CACHE.write_text(json.dumps({"T001": {"at": old, "tier": "primary", "url": "x", "rows": GOOD_BANK}}))
    monkeypatch.setattr(live, "read_live", boom)
    assert live.resolve(BANK, ANCHOR)["tier"] != "cache"


def test_backup3_archive(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    monkeypatch.setattr(live, "read_archive", lambda kind, url: (GOOD_BANK, "wayback 20261014"))
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "archive" and r["as_of"] == "wayback 20261014"


def test_all_fail_bank_shows_labelled_boc_and_cu_shows_unavailable(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    b = live.resolve(BANK, ANCHOR)
    assert b["tier"] == "boc_typical" and b["lender_specific"] is False and b["five_year"]["posted"] == 6.19
    c = live.resolve(CU, ANCHOR)
    assert c["tier"] == "unavailable" and c["five_year"]["advertised"] is None
    assert [t["tier"] for t in c["tried"]] == ["primary", "backup1", "cache", "archive"]


def test_validation_rejects_bad_readings_and_moves_on(monkeypatch):
    far = [(60, "fixed_closed", "posted", 9.99)]                         # far from the BoC big-six figure
    swapped = [(60, "fixed_closed", "posted", 4.49), (60, "fixed_closed", "special", 6.49)]
    assert not live.validate(far, "bank", ANCHOR)[0]
    assert not live.validate(swapped, "bank", ANCHOR)[0]
    assert not live.validate([(60, "fixed_closed", "posted", 3.10)], "credit_union", ANCHOR)[0]   # below bond + 0.3
    assert live.validate(GOOD_CU, "credit_union", ANCHOR)[0]
    calls = iter([far, GOOD_BANK])
    monkeypatch.setattr(live, "read_live", lambda kind, url: next(calls))
    r = live.resolve(BANK_B1, ANCHOR)
    assert r["tier"] == "backup1" and r["tried"][0]["ok"] is False


def test_refresh_and_api(monkeypatch):
    monkeypatch.setattr(live, "market_anchor", lambda: ANCHOR)
    monkeypatch.setattr(live, "LENDERS", [BANK, CU])
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK if "bank" in url else GOOD_CU)
    client = TestClient(app)
    b = client.post("/api/ratewatch/live/refresh").json()
    assert [r["name"] for r in b["banks"]] == ["Test Bank"] and b["credit_unions"][0]["five_year"]["advertised"] == 4.84
    again = client.get("/api/ratewatch/live").json()
    assert again["refreshed_at"] == b["refreshed_at"] and again["stale"] is False


def test_registry_is_banks_and_credit_unions_only():
    assert {t for _, _, t, _, _ in live.LENDERS} == {"bank", "credit_union"}
    assert sum(t == "bank" for _, _, t, _, _ in live.LENDERS) == 6
```

## Frontend tests
`tests/live-rates.test.mjs` (56 lines)

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {liveRatesView, ageText} from '../frontend/js/live-rates.js';

const row = (over) => ({id: 'P021', name: 'RBC', type: 'bank', tier: 'primary', tier_label: 'Live', as_of: '2026-10-15T03:00:00+00:00',
  source_url: 'https://www.rbcroyalbank.com/mortgages/mortgage-rates.html', lender_specific: true,
  rates: {'12': {posted: 5.74, special: 5.14}, '36': {posted: 6.25, special: 4.99}, '60': {posted: 6.19, special: 5.14}},
  five_year: {posted: 6.19, special: 5.14, advertised: 5.14}, tried: [{tier: 'primary', ok: true, reason: 'ok'}], ...over});

const board = {refreshed_at: '2026-10-15T03:00:00+00:00', anchor: {boc_5y_posted: 6.19, goc_5y: 3.55, boc_5y_posted_date: '2026-10-14'},
  banks: [row(), row({id: 'P027', name: 'BMO', tier: 'boc_typical', tier_label: 'Bank of Canada big-six typical', lender_specific: false,
    tried: [{tier: 'primary', ok: false, reason: 'ReadTimeout'}]})],
  credit_unions: [row({id: 'CU01', name: 'Meridian', type: 'credit_union', five_year: {posted: 6.49, special: 4.74, advertised: 4.74}}),
    row({id: 'CU04', name: 'Servus', type: 'credit_union', tier: 'unavailable', tier_label: 'Unavailable', lender_specific: false,
      rates: {}, five_year: {}, source_url: null})]};

test('banks show posted and special, credit unions show advertised', () => {
  const html = liveRatesView({liveRates: board});
  assert.match(html, /6\.19%/);
  assert.match(html, /5\.14%/);
  assert.match(html, /4\.74%/);
  assert.match(html, /5-yr advertised/);
});

test('non-lender-specific and unavailable rows are clearly marked', () => {
  const html = liveRatesView({liveRates: board});
  assert.match(html, /Bank of Canada big-six typical \*/);
  assert.match(html, /Unavailable/);
});

test('each attempt is visible on hover', () => {
  assert.match(liveRatesView({liveRates: board}), /title="primary: ReadTimeout"/);
});

test('age text', () => {
  const now = new Date('2026-10-15T05:00:00Z');
  assert.equal(ageText('2026-10-15T04:30:00+00:00', now), '30 min ago');
  assert.equal(ageText('2026-10-15T01:00:00+00:00', now), '4 h ago');
  assert.equal(ageText('wayback 20261014', now), 'wayback 20261014');
});

test('loading and error states', () => {
  assert.match(liveRatesView({}), /Loading current rates/);
  assert.match(liveRatesView({liveRatesError: 'offline'}), /offline/);
});

test('page is registered, cached offline and wired to the API', () => {
  const html = readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  const sw = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../frontend/js/app.js', import.meta.url), 'utf8');
  assert.match(html, /data-nav="live"/);
  assert.match(sw, /\/js\/live-rates\.js/);
  assert.match(sw, /\/js\/lender-exact\.js/);
  assert.match(app, /live-rates-refresh/);
});
```
