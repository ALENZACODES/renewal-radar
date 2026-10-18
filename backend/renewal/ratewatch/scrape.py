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

def _get(url, timeout=30, **kw):
    headers = {**UA, **kw.pop("headers", {})}
    return requests.get(url, headers=headers, timeout=timeout, **kw)


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
            timeout = kw.pop("timeout", 60)
            headers = {**UA, **kw.pop("headers", {})}
            r = requests.get(url, headers=headers, timeout=timeout, **kw)
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


def equitable_rows(html: str) -> list:
    """Equitable Bank's own rate page (equitablebank.ca/mortgage-rates): a table with terms across the top.
    'Standard Mortgage Rate' is the posted rate; other product rows (EQB Evolution) are offered rates.
    The page also lists reverse-mortgage rates and APRs; those sit in other tables and are ignored."""
    from bs4 import BeautifulSoup
    out = []
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        head = next((r for r in rows if sum(bool(re.search(r"(Year|Month)", c)) for c in r) >= 4), None)
        if head is None or not any("Mortgage" in r[0] for r in rows if r):
            continue
        for r in rows:
            if r is head or not r or "APR" in r[0] or "Reverse" in r[0]:
                continue
            rtype = "posted" if r[0].lower().startswith("standard") else "special"
            for label, cell in zip(head[1:], r[1:]):
                m = re.match(r"(\d+)\s*(Year|Month)\s*(Fixed|Adjustable)?", label)
                v = re.match(r"\s*(\d{1,2}\.\d{1,3})\s*%", cell)
                if not m or not v:
                    continue
                months = int(m.group(1)) * (12 if m.group(2) == "Year" else 1)
                kind = "variable" if m.group(3) == "Adjustable" else "fixed_closed"
                out.append((months, kind, rtype, float(v.group(1))))
    return out


def coast_rows(html: str) -> list:
    """Coast Capital (coastcapitalsavings.com/rates/mortgages): each table is labelled only by the H3 above it.
    'Posted rates - Fixed Rate Mortgages' = posted (used in term-break calculations); 'Fixed Rate Mortgages' = offered.
    The first rate column is the up-to-25-year amortization rate; APR columns and open/high-ratio rows are excluded."""
    from bs4 import BeautifulSoup
    out = []
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        head = table.find_previous(["h2", "h3", "h4"])
        title = head.get_text(" ", strip=True).lower() if head else ""
        if "fixed rate mortgages" not in title:
            continue
        rtype = "posted" if title.startswith("posted") else "special"
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(cells) < 2:
                continue
            m = re.match(r"(\d+)-Year Fixed Rate", cells[0])
            v = re.match(r"(\d{1,2}\.\d{1,3})\s*%", cells[1])
            if m and v and not re.search(r"open|high", cells[0], re.I):
                out.append((int(m.group(1)) * 12, "fixed_closed", rtype, float(v.group(1))))
    return out


def duca_pdf_rows(pdf: bytes) -> list:
    """DUCA's own posted-rate notice (PDF 'Early Prepayment Charges and Interest Rate Differential (IRD)'):
    'DUCA Posted Mortgage Rates-Effective <date>' / 'Term 1 Year Fixed ... 5 Year Fixed' / 'Posted Rate 5.34% ...'.
    These are the rates DUCA's IRD clause uses (posted rate for a term equal to the remaining term)."""
    import io
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    terms = [int(t) * 12 for t in re.findall(r"(\d+)\s*Year\s*Fixed", text, re.I)]
    m = re.search(r"Posted\s*Rate\s*\d?\s*((?:\s*\d{1,2}\.\d{1,3}\s*%)+)", text, re.I)   # "Posted Rate1" footnote
    if not terms or not m:
        return []
    rates = [float(x) for x in re.findall(r"(\d{1,2}\.\d{1,3})\s*%", m.group(1))]
    return [(t, "fixed_closed", "posted", r) for t, r in zip(terms, rates)]
