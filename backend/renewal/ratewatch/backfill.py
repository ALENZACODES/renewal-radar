"""Five-year, month-by-month posted-rate history for the big six from public web archives.

    python -m renewal.ratewatch.backfill              # run (resumable; safe to stop and restart any time)
    python -m renewal.ratewatch.backfill --report     # coverage report + grade only, no network

Why several sources per bank: TD, BMO, CIBC and Scotiabank render rates with JavaScript, so their archived
*pages* are empty; their archived *data feeds* hold the numbers. Only each bank's own pages and feeds are used
(no third-party rate sites). Months with no bank-own capture stay as listed gaps - never filled by estimation. Every saved value must pass validate_month():
the 5-year posted rate must sit within MAX_GAP of the Bank of Canada big-six figure for the same week.

Politeness: one archive request every PACE seconds. On HTTP 429 the job sleeps BLOCK_WAIT, probes, and resumes.
"""
import json, re, sys, time
from datetime import date, datetime, timedelta
import requests
from .paths import DATA
from .linkcheck import UA
from .parse import extract_rates
from . import history, scrape

YEARS = 5
PACE = 30.0                         # ~9 hours for the full 5-year pass; gentle on the archive
BLOCK_WAIT = 15 * 60
MAX_GAP = 0.75                      # % points from the BoC big-six figure a bank's 5-yr posted may sit
PROGRESS = DATA / "backfill_progress.json"
PARSER_VERSION = "2026-10-16a"        # bump when parse() changes: earlier rejections are then retried
COVERAGE = DATA / "history_coverage.json"
CDX = "https://web.archive.org/cdx/search/cdx"

# source id -> ordered list of (parser, url, match): match="prefix" collects every archived URL variant
SOURCES = {
    "P021": [("html", "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html", "exact")],
    "P023": [("td_json", "https://ix0.apps.td.com/api/get-rates/en", "exact")],
    "P025": [("scotia_json", "https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage", "exact")],
    "P027": [("bmo_epm", "https://www.bmo.com/public-data/api/epm/v1.0/bmo-epm-mortgage.json", "exact"),
             ("json_generic", "https://www.bmo.com/public-data/api/v1.1/mortgages.json", "exact")],
    "P029": [("cibc_js", "https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy?lobId=5", "prefix")],
    "P031": [("html", "https://www.nbc.ca/personal/mortgages/rates.html", "exact")],
}


def months():
    today = date.today().replace(day=1)
    out, d = [], today.replace(year=today.year - YEARS)
    while d <= today:
        out.append(d.strftime("%Y%m"))
        d = (d + timedelta(days=32)).replace(day=1)
    return out


class Archive:
    """Rate-limited, block-aware archive client."""
    def __init__(self):
        self.last = 0.0

    MAX_TRIES = 6                       # then give up on this request; the caller leaves it for the next run

    def get(self, url, params=None, timeout=120):
        """Returns a response, or None after MAX_TRIES failures. Every failure is logged (never a silent loop)."""
        for attempt in range(1, self.MAX_TRIES + 1):
            wait = PACE - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = requests.get(url, params=params, headers=UA, timeout=timeout)
            except requests.RequestException as e:
                pause = min(60 * 2 ** (attempt - 1), BLOCK_WAIT)
                print(f"{datetime.now():%H:%M} archive connection {type(e).__name__} (try {attempt}/{self.MAX_TRIES}); "
                      f"waiting {pause // 60} min", flush=True)
                time.sleep(pause)
                continue
            if r.status_code in (429, 503):
                print(f"{datetime.now():%H:%M} archive busy ({r.status_code}, try {attempt}/{self.MAX_TRIES}); "
                      f"waiting {BLOCK_WAIT // 60} min", flush=True)
                time.sleep(BLOCK_WAIT)
                continue
            return r
        print(f"{datetime.now():%H:%M} giving up on {url[:90]} for this run", flush=True)
        return None


def captures(arc, url, match):
    """{YYYYMM: [(timestamp, original_url), ...]} for the window, newest-first within a month."""
    params = {"url": url.split("://", 1)[1] if match == "exact" else url.split("://", 1)[1],
              "output": "json", "from": months()[0], "filter": "statuscode:200", "fl": "timestamp,original"}
    if match == "prefix":
        params["matchType"] = "prefix"
    else:
        params["collapse"] = "timestamp:8"
    r = arc.get(CDX, params=params)
    out = {}
    if r is None:
        return out                                          # empty -> not cached, retried next run
    try:
        rows = r.json()[1:]
    except ValueError:
        return out
    for ts, orig in rows:
        if match == "prefix" and ("FRCM" not in orig.upper()):
            continue
        out.setdefault(ts[:6], []).append((ts, orig))
    for k in out:
        out[k].sort(reverse=True)
    return out


def _walk_json(obj, found):
    """Generic: find {term..., rate...}-like leaves in any JSON feed (used for BMO's older feed)."""
    if isinstance(obj, dict):
        keys = {k.lower(): k for k in obj}
        term_k = next((keys[k] for k in keys if k in ("term", "term_months", "termmonths", "termlength")), None)
        rate_k = next((keys[k] for k in keys if k in ("rate", "value", "postedrate", "posted_rate")), None)
        if term_k and rate_k:
            try:
                t = str(obj[term_k]).lower()
                n = float(re.findall(r"[\d.]+", t)[0])
                if "month" in term_k.lower() or "month" in t or "mois" in t:
                    months_ = int(n)                               # term_months / "6 months": already months
                else:
                    months_ = int(n if n > 12 else n * 12)         # "5", "5 year": years
                label = json.dumps(obj).lower()
                if "open" not in label and "variable" not in label and "convertible" not in label:
                    found.append((months_, "fixed_closed", "special" if "special" in label else "posted", float(obj[rate_k])))
            except (IndexError, ValueError, TypeError):
                pass
        for v in obj.values():
            _walk_json(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json(v, found)
    return found


def parse(kind, text):
    try:
        if kind == "html":
            return extract_rates(text)
        if kind == "cibc_js":
            return scrape.cibc_rows(text)
        js = json.loads(text)
        if kind == "scotia_json":
            return scrape.scotia_rows(js)
        if kind == "bmo_epm":
            return scrape.bmo_posted_rows(js)
        if kind == "bmo_flat":                 # bmo.com/main/personal/mortgages/json/rates: {"fixed-5-year-closed": "5.34", ...}
            rows = []
            for k, v in js.items():
                m = re.fullmatch(r"fixed-(\d+)-year-closed", k)
                if m:
                    rows.append((int(m.group(1)) * 12, "fixed_closed", "posted", float(v)))
            return rows
        if kind == "td_json":
            rows = []
            for cat in js.get("categories", []):
                for sub in cat.get("subcategories", []):
                    if sub.get("id") == "Fixed Rate Closed Mortgage":
                        rows += [(int(round(float(r["term"]) * 12)), "fixed_closed", "posted", float(r["rate"])) for r in sub.get("rates", [])]
            return rows
        if kind == "json_generic":
            return _walk_json(js, [])
    except (ValueError, KeyError, TypeError):
        return []
    return []


def boc_on(day):
    t, _ = history.table_on("BIG6_TYPICAL", day, max_age_days=10)
    return t.get(60)


def validate_month(rows, day):
    """Accept only if a 5-yr fixed posted exists and sits within MAX_GAP of the BoC big-six figure that week."""
    posted = {t: r for t, k, rt, r in rows if k == "fixed_closed" and rt == "posted"}
    boc = boc_on(day)
    if 60 not in posted or boc is None:
        return False, posted.get(60), boc
    return abs(posted[60] - boc) <= MAX_GAP, posted[60], boc


LOCK = DATA / "backfill.lock"


def _single_instance():
    """Refuse to start if another backfill is alive (two jobs double the load and trigger archive blocks)."""
    import os
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)                      # raises if the process is gone
            raise SystemExit(f"backfill already running (pid {pid}); not starting a second one")
        except (ValueError, OSError):
            pass                                 # stale lock
    LOCK.write_text(str(os.getpid()))


def run():
    _single_instance()
    try:
        _run()
    finally:
        LOCK.unlink(missing_ok=True)


CC_INDEX = "https://index.commoncrawl.org/collinfo.json"


def cc_crawls():
    """Common Crawl crawls inside the window (each crawl has its own CDX index)."""
    first = months()[0]
    out = []
    listing = []
    for attempt in range(3):
        try:
            listing = requests.get(CC_INDEX, timeout=60).json()
            break
        except (requests.RequestException, ValueError):
            time.sleep(30 * (attempt + 1))
    for c in listing:                                       # unreachable -> [] : skip Common Crawl, never crash
        try:
            yr, wk = c["id"].split("-")[2:4]                 # CC-MAIN-2026-39
            approx = date(int(yr), 1, 1) + timedelta(weeks=int(wk) - 1)
        except ValueError:
            continue                                         # old crawls use other id formats; outside the window anyway
        if approx.strftime("%Y%m") >= first:
            out.append(c["cdx-api"])
    return out


def cc_pass(prog):
    """Common Crawl: a second, independent public archive. Fill months from it first (not rate-limited like Wayback)."""
    import gzip, io
    crawls = cc_crawls()
    for sid, sources in SOURCES.items():
        done = prog.setdefault(sid, {})
        for kind, url, match in sources:
            key = f"cc:{sid}:{url}"
            if not prog.get(key):
                caps = {}
                for api in crawls:
                    params = {"url": url.split("://", 1)[1], "output": "json"}
                    if match == "prefix":
                        params["matchType"] = "prefix"
                    try:
                        r = requests.get(api, params=params, timeout=60)
                    except requests.RequestException:
                        continue
                    for line in r.text.splitlines():
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if rec.get("status") != "200" or (match == "prefix" and "FRCM" not in rec.get("url", "").upper()):
                            continue
                        caps.setdefault(rec["timestamp"][:6], []).append(
                            {k: rec[k] for k in ("timestamp", "filename", "offset", "length", "url")})
                    time.sleep(1)
                prog[key] = caps
                PROGRESS.write_text(json.dumps(prog, indent=1))
            for month, recs in sorted(prog[key].items()):
                if month not in months() or isinstance(done.get(month), dict):
                    continue
                for rec in sorted(recs, key=lambda x: x["timestamp"], reverse=True)[:3]:
                    s0, n = int(rec["offset"]), int(rec["length"])
                    try:
                        raw = requests.get("https://data.commoncrawl.org/" + rec["filename"], timeout=120,
                                           headers={"Range": f"bytes={s0}-{s0 + n - 1}"}).content
                        warc = gzip.GzipFile(fileobj=io.BytesIO(raw)).read().decode("utf-8", "replace")
                    except Exception:
                        continue
                    body = warc.split("\r\n\r\n", 2)[-1]  # WARC headers, HTTP headers, then the body
                    rows = parse(kind, body)
                    day = datetime.strptime(rec["timestamp"][:8], "%Y%m%d").date()
                    ok, rate5, boc = validate_month(rows, day)
                    print(f"{sid} {rec['timestamp'][:8]} cc/{kind:10} rows={len(rows):3} 5y={rate5} boc={boc} {'OK' if ok else 'reject'}", flush=True)
                    time.sleep(1)
                    if ok:
                        history.save(sid, day.isoformat(), rows, "commoncrawl")
                        done[month] = {"how": f"commoncrawl/{kind}", "ts": rec["timestamp"], "url": rec["url"], "rate5": rate5, "boc": boc}
                        break
                PROGRESS.write_text(json.dumps(prog, indent=1))
                report(prog)


ARQUIVO_CDX = "https://arquivo.pt/wayback/cdx"
ARQUIVO_PACE = 8.0
# Arquivo.pt (Portugal's national web archive) crawls these bank-own pages and feeds too, under its own limits.
# Extra bank-own URLs it holds that Wayback does not, tried after the SOURCES above.
ARQUIVO_EXTRA = {
    "P021": [("html", "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html", "prefix")],
    "P023": [("html", "https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates", "prefix")],
    "P027": [("bmo_flat", "https://www.bmo.com/main/personal/mortgages/json/rates", "prefix"),
             ("html", "https://www.bmo.com/main/personal/mortgages/mortgage-rates/", "prefix")],
    "P029": [("html", "https://www.cibc.com/en/personal-banking/mortgages/mortgage-rates.html", "prefix"),
             ("html", "https://www.cibc.com/en/personal-banking/mortgages/find-mortgage-rates.html", "prefix")],
}


def arquivo_pass(prog):
    """Arquivo.pt: an independent public archive with its own rate limit. Same bank-own sources, same validation."""
    for sid in SOURCES:
        done = prog.setdefault(sid, {})
        for kind, url, match in SOURCES[sid] + ARQUIVO_EXTRA.get(sid, []):
            key = f"pt:{sid}:{url}"
            if not prog.get(key):
                caps = {}
                params = {"url": url.split("://", 1)[1] + ("*" if match == "prefix" else ""), "output": "json",
                          "filter": "status:200"}
                for attempt in range(3):
                    try:
                        r = requests.get(ARQUIVO_CDX, params=params, headers=UA, timeout=90)
                        break
                    except requests.RequestException:
                        time.sleep(60 * (attempt + 1))
                else:
                    print(f"{sid} arquivo index unreachable for {url}; retry next run", flush=True)
                    continue
                for line in r.text.splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if kind == "cibc_js" and "FRCM" not in rec.get("url", "").upper():
                        continue
                    caps.setdefault(rec["timestamp"][:6], []).append([rec["timestamp"], rec["url"]])
                prog[key] = caps
                PROGRESS.write_text(json.dumps(prog, indent=1))
                time.sleep(ARQUIVO_PACE)
            tried = prog.setdefault(f"pt-tried:{sid}:{PARSER_VERSION}", [])
            for month, recs in sorted(prog[key].items()):
                if month not in months() or isinstance(done.get(month), dict):
                    continue
                for ts, orig in sorted(recs, reverse=True)[:3]:
                    if ts in tried:
                        continue
                    try:
                        resp = requests.get(f"https://arquivo.pt/wayback/{ts}id_/{orig}", headers=UA, timeout=90)
                    except requests.RequestException as e:
                        print(f"{sid} {ts[:8]} arquivo error {type(e).__name__}; will retry", flush=True)
                        time.sleep(ARQUIVO_PACE)
                        continue
                    time.sleep(ARQUIVO_PACE)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        print(f"{sid} arquivo busy ({resp.status_code}); waiting 5 min", flush=True)
                        time.sleep(300)
                        continue
                    rows = parse(kind, resp.text) if resp.ok else []
                    day = datetime.strptime(ts[:8], "%Y%m%d").date()
                    ok, rate5, boc = validate_month(rows, day)
                    if resp.ok and rows and boc is None:
                        continue
                    tried.append(ts)
                    print(f"{sid} {ts[:8]} pt/{kind:10} rows={len(rows):3} 5y={rate5} boc={boc} {'OK' if ok else 'reject'}", flush=True)
                    if ok:
                        history.save(sid, day.isoformat(), rows, "arquivo")
                        done[month] = {"how": f"arquivo/{kind}", "ts": ts, "url": orig, "rate5": rate5, "boc": boc}
                        break
                PROGRESS.write_text(json.dumps(prog, indent=1))
                report(prog)


def _run():
    try:
        history.official(start=f"{date.today().year - YEARS}-01-01")
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"Bank of Canada refresh skipped ({type(e).__name__}); using stored figures", flush=True)
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    if "--no-cc" not in sys.argv:
        cc_pass(prog)
    if "--no-pt" not in sys.argv:
        arquivo_pass(prog)
    arc = Archive()
    for sid, sources in SOURCES.items():
        done = prog.setdefault(sid, {})                          # month -> {"how","ts","url","rate5","boc"} or "tried"
        for kind, url, match in sources:
            key = f"caps:{sid}:{url}"
            if not prog.get(key):                                 # empty / failed discovery is retried next run
                prog[key] = captures(arc, url, match)
                PROGRESS.write_text(json.dumps(prog, indent=1))
            for month in months():
                if isinstance(done.get(month), dict):
                    continue
                tried = prog.setdefault(f"tried:{sid}:{PARSER_VERSION}", [])
                for ts, orig in prog[key].get(month, [])[:3]:      # up to 3 captures per month per source
                    if ts in tried:
                        continue
                    try:
                        r = arc.get(f"https://web.archive.org/web/{ts}id_/{orig}")
                    except Exception as e:                         # never let one capture stop the run
                        print(f"{sid} {ts[:8]} error {type(e).__name__}; will retry", flush=True)
                        continue
                    if r is None or r.status_code >= 500:
                        continue                                   # transient: leave untried so a restart retries it
                    rows = parse(kind, r.text) if r.ok else []
                    day = datetime.strptime(ts[:8], "%Y%m%d").date()
                    ok, rate5, boc = validate_month(rows, day)
                    if r.ok and rows and boc is None:
                        continue                                   # no BoC figure yet: not judged, retry later
                    tried.append(ts)                               # judged (accepted/rejected) or a definitive 4xx
                    print(f"{sid} {ts[:8]} {kind:12} rows={len(rows):3} 5y={rate5} boc={boc} {'OK' if ok else 'reject'}", flush=True)
                    if ok:
                        history.save(sid, day.isoformat(), rows, "wayback")
                        done[month] = {"how": kind, "ts": ts, "url": orig, "rate5": rate5, "boc": boc}
                        break
                PROGRESS.write_text(json.dumps(prog, indent=1))
                report(prog)
    report(prog)


def report(prog=None):
    prog = prog if prog is not None else (json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {})
    ms = months()
    out = {"window": f"{ms[0]}-{ms[-1]}", "months": len(ms), "banks": {}}
    for sid in SOURCES:
        got = {m: v for m, v in prog.get(sid, {}).items() if isinstance(v, dict)}
        got = {m: v for m, v in got.items() if m in ms}
        out["banks"][sid] = {"covered": len(got), "share": round(len(got) / len(ms), 3),
                             "gaps": [m for m in ms if m not in got],
                             "by_source": {k: sum(1 for v in got.values() if v["how"] == k) for k in {v["how"] for v in got.values()}}}
    shares = [b["share"] for b in out["banks"].values()]
    out["min_share"] = min(shares) if shares else 0
    out["grade"] = "A" if out["min_share"] >= 0.95 else "B" if out["min_share"] >= 0.85 else "C" if out["min_share"] >= 0.7 else "D"
    COVERAGE.write_text(json.dumps(out, indent=2))
    return out


def supervise(max_hours=10.0):
    """Run to completion; on an unexpected error wait 5 minutes and resume from saved progress."""
    import traceback
    deadline = time.time() + max_hours * 3600
    while time.time() < deadline:
        try:
            run()
            print(f"{datetime.now():%H:%M} backfill pass complete", flush=True)
            return
        except SystemExit:
            raise
        except Exception:
            print(f"{datetime.now():%H:%M} unexpected error, resuming in 5 min: {traceback.format_exc()}", flush=True)
            LOCK.unlink(missing_ok=True)
            time.sleep(300)


if __name__ == "__main__":
    if "--report" in sys.argv:
        r = report()
        print(json.dumps({k: v for k, v in r.items() if k != "banks"}, indent=1))
        for sid, b in r["banks"].items():
            print(sid, b["covered"], "/", r["months"], b["by_source"])
    else:
        supervise()
