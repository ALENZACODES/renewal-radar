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
import os
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


def _try_os_lock(fh) -> bool:
    """Non-blocking exclusive lock on byte 0 of an open file. Held until the handle closes or the process dies."""
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def refresh(lenders=None) -> dict:
    """One collection at a time, across threads and processes. The lock file is never deleted: the operating system
    releases the lock when its holder finishes or dies, so there is no stale-lock cleanup that could race."""
    if not _refresh_lock.acquire(blocking=False):
        with _refresh_lock:                                   # wait for the in-flight refresh, then reuse it
            return _load(BOARD)
    try:
        fh = open(REFRESH_LOCK, "a+b")
        try:
            if not _try_os_lock(fh):                          # another process is collecting
                return _load(BOARD) or {"refreshed_at": None, "banks": [], "credit_unions": [], "busy": True}
            try:
                return _refresh(lenders)
            finally:
                _os_unlock(fh)
        finally:
            fh.close()
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
