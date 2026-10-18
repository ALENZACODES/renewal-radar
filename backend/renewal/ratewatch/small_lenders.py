"""Parsers for smaller lenders' own rate pages (credit unions, trust companies, B lenders).

Each returns rows (term_months, kind, rtype, rate). rtype is 'posted' for posted rates (the ones an IRD uses) and
'special' for offered or broker base rates. A parser returns [] when the page layout no longer matches, so the live
chain moves on to the next source instead of saving a wrong number.
"""
import json
import re

from bs4 import BeautifulSoup

PCT = re.compile(r"(\d{1,2}\.\d{1,3})\s*%?")


def _term_months(label: str):
    m = re.search(r"(\d+)[\s-]*(year|yr|month|mo)", label, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n if m.group(2).lower().startswith("mo") else n * 12


def servus_rows(html: str) -> list:
    """servus.ca/rates: the mortgage tab (div.catSection[data-catid=3]) sits in the raw HTML below the GIC tab.
    Rows are div.row.rate with spans: term | posted 'Rate' | 'Special Rate'. Headings separate closed/open/No Frills."""
    soup = BeautifulSoup(html, "html.parser")
    sec = soup.select_one('div.catSection[data-catid="3"]')
    if sec is None:
        return []
    out, kind = [], None
    for el in sec.select(".productHeading, div.row.rate"):
        if "productHeading" in (el.get("class") or []):
            h = el.get_text(" ", strip=True).lower()
            kind = "fixed_closed" if "closed" in h else "open" if "open" in h else None   # No Frills: separate product
            continue
        if kind is None:
            continue
        cells = [c.get_text(" ", strip=True) for c in el.find_all("span")]
        if len(cells) < 2:
            continue
        months = _term_months(cells[0])
        if months is None:
            continue
        insured = "high ratio" in cells[0].lower()
        for rtype, cell in (("posted", cells[1]), ("special", cells[2] if len(cells) > 2 else "")):
            v = PCT.search(cell)
            if v:
                out.append((months, kind, rtype + ("_insured" if insured else ""), float(v.group(1))))
    return out


def term_row_rows(html: str) -> list:
    """A sideways table: one row of terms ('Term (Closed) | 1 Year | 2 Years ...'), the next row of rates
    ('Rate | 5.24% ...'). Used by Community Trust and Questbank (communitytrust.com). These are posted closed rates."""
    out = []
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        for head, vals in zip(rows, rows[1:]):
            if not head or "term" not in head[0].lower() or not vals or "rate" not in vals[0].lower():
                continue
            kind = "open" if "open" in head[0].lower() else "fixed_closed"
            for label, cell in zip(head[1:], vals[1:]):
                months, v = _term_months(label), PCT.search(cell)
                if months and v and "%" in cell:
                    out.append((months, kind, "posted", float(v.group(1))))
    return out


# CMLS <option value> codes -> (months, kind). Codes come from the page's own rate selector.
CMLS_CODES = {"1": (12, "fixed_closed"), "2": (24, "fixed_closed"), "3": (36, "fixed_closed"), "4": (48, "fixed_closed"),
              "5": (60, "fixed_closed"), "15": (72, "fixed_closed"), "6": (84, "fixed_closed"), "7": (120, "fixed_closed"),
              "8": (36, "variable"), "9": (60, "variable")}
CMLS_UNINSURED = {"25": 12, "26": 24, "27": 36, "29": 48, "16": 60}


def cmls_rows(html: str) -> list:
    """cmls.ca residential rates: an inline `var MortgageRates={...};` keyed by the selector's option codes.
    Offered rates (insured/qualifying); the uninsured closed rates are kept as their own rate type."""
    m = re.search(r"var\s+MortgageRates\s*=\s*(\{.*?\})\s*;", html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for group in ("Fixed Rate Mortgage", "Adjustable Rate Mortgage"):
        for item in data.get(group, []):
            code, rate = str(item.get("Term")), item.get("Rate")
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                continue
            if code in CMLS_CODES:
                months, kind = CMLS_CODES[code]
                out.append((months, kind, "special", rate))
            elif code in CMLS_UNINSURED:
                out.append((CMLS_UNINSURED[code], "fixed_closed", "special_uninsured", rate))
    return out


def rfa_rows(html: str) -> list:
    """rfa.ca/prime: 'Standard Rates' table, rows '<n> Year Fixed' then LTV columns. The first column is the
    insured rate; it is kept as the offered rate. Promotions and ARM (prime-minus) rows are not used."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    i = text.find("Standard Rates")
    if i < 0:
        return []
    seen = {}
    for n, rate in re.findall(r"\b(\d{1,2}) Year Fixed\s+(\d{1,2}\.\d{2})%", text[i:i + 4000]):
        seen.setdefault(int(n) * 12, float(rate))          # first row per term = the standard product
    return [(t, "fixed_closed", "special", r) for t, r in sorted(seen.items())]


def wealthone_rows(pdf: bytes) -> list:
    """WealthONE's one-page broker rate sheet PDF ('BASE RATES Effective <date>'). Its two columns (Fixed, Variable)
    are interleaved in the text layer, so each rate is paired with the term label on the same line by position."""
    import pymupdf
    try:
        page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    except Exception:                                      # noqa: BLE001 - not a PDF / layout changed
        return []
    words = page.get_text("words")
    headers = {w[4]: w[0] for w in words if w[4] in ("Fixed", "Variable")}
    if "Fixed" not in headers or "Variable" not in headers:
        return []
    split = (headers["Fixed"] + headers["Variable"]) / 2
    labels, rates = [], []
    for k, w in enumerate(words):
        x, y, txt = w[0], (w[1] + w[3]) / 2, w[4]
        if txt.isdigit() and k + 1 < len(words) and words[k + 1][4] == "Year" and y < 400:
            labels.append((x < split, y, int(txt) * 12))
        elif re.fullmatch(r"\d{1,2}\.\d{2}%", txt) and y < 400:
            rates.append((x < split, y, float(txt[:-1])))
    out = []
    for fixed_col, y, months in labels:
        near = [r for r in rates if r[0] == fixed_col and abs(r[1] - y) <= 5]
        if near:
            rate = min(near, key=lambda r: abs(r[1] - y))[2]
            out.append((months, "fixed_closed" if fixed_col else "variable", "special", rate))
    return out


def bridgewater_rows(html: str) -> list:
    """bwbbrokerinfo.ca/mortgage-rates: alternative ('Gateway') rates by credit score; cells carry no % sign.
    The best credit tier's AIR row is kept as the offered rate (1-3 year terms only)."""
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        if not rows or "credit score" not in rows[0][0].lower():
            continue
        terms = [_term_months(h) for h in rows[0]]
        for r in rows[1:]:
            if len(r) > 2 and r[1].upper() == "AIR" and r[0].strip():
                out = []
                for months, cell in zip(terms, r):
                    if months and re.fullmatch(r"\d{1,2}\.\d{1,3}", cell):
                        out.append((months, "fixed_closed", "special", float(cell)))
                return out                                 # first AIR row = best credit tier
    return []


def hana_rows(html: str) -> list:
    """hanabank.ca/pb/pu/pbpu008s01: rates live in inline `var pbpuJsonObjNN = JSON.parse('...')`.
    The object whose records say irtLocalNm 'Posted Rate' holds posted fixed rates; ctt = '1Year'..'5Year'."""
    out = []
    for body in re.findall(r"var\s+pbpuJsonObj\d+\s*=\s*JSON\.parse\('(.*?)'\);", html, re.S):
        try:
            recs = json.loads(body).get("rec", [])
        except ValueError:
            continue
        for r in recs:
            if "posted" not in str(r.get("irtLocalNm", "")).lower():
                continue
            months = _term_months(str(r.get("ctt", "")))
            try:
                rate = float(r.get("gBascIrt"))
            except (TypeError, ValueError):
                continue
            if months:
                out.append((months, "fixed_closed", "posted", round(rate, 3)))
    return out


def bloom_rows(text: str) -> list:
    """api.bloomfin.ca/api/rates (feeds bloomfin.ca/rate-and-fees): reverse-mortgage rates as JSON.
    *ResetRate = the standard 'Bloom Rate'; the plain *Rate fields can be promotional. Both are offered rates."""
    try:
        d = json.loads(text)
    except ValueError:
        return []
    out = []
    for key, months in (("oneYear", 12), ("threeYear", 36), ("fiveYear", 60)):
        for field, rtype in ((key + "ResetRate", "special"), (key + "Rate", "special_promo")):
            v = d.get(field)
            if isinstance(v, (int, float)) and v > 0:
                out.append((months, "fixed_closed", rtype, float(v)))
    return out


def antrim_rows(html: str) -> list:
    """antriminvestments.com/lending-guidelines: private first/second mortgages by LTV, open 1-year terms.
    The lowest-LTV first-mortgage rate is kept as the offered rate; second mortgages are not mixed in."""
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        if not rows or len(rows[0]) < 2 or "1st" not in rows[0][1]:
            continue
        for r in rows[1:]:
            v = PCT.search(r[1]) if len(r) > 1 else None
            if v and r[0].strip().endswith("%"):
                return [(12, "open", "special", float(v.group(1)))]
    return []


def atrium_rows(html: str) -> list:
    """atriummic.com/residential-products: '1st <= 65% 6.49% 1.75%' (rate then lender fee), 1-year terms."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"PURCHASES\s+1st\s*\S*\s*\d+%\s+(\d{1,2}\.\d{2})%", text)
    return [(12, "fixed_closed", "special", float(m.group(1)))] if m else []


def hillmount_rows(html: str, prime: float | None = None) -> list:
    """hillmount.ca broker FAQ: 'Our rates start at prime plus 2.50% for 1st mortgages' (terms up to 12 months).
    The offered rate is the current prime rate plus that spread."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"prime plus\s+(\d+(?:\.\d+)?)%\s+for 1st", text, re.I)
    if not m:
        return []
    if prime is None:
        prime = current_prime()
    return [(12, "fixed_closed", "special", round(prime + float(m.group(1)), 2))] if prime else []


def current_prime():
    """Big-six prime (Bank of Canada series) from the stored history; None if not loaded."""
    from datetime import date
    from . import history
    t, _ = history.table_on("BIG6_TYPICAL", date.today(), rtype="posted", kind="prime", max_age_days=21)
    return t.get(0)


PARSERS = {"servus": servus_rows, "term_row": term_row_rows, "cmls": cmls_rows, "rfa": rfa_rows,
           "bridgewater": bridgewater_rows, "hana": hana_rows, "bloom": bloom_rows, "antrim": antrim_rows,
           "atrium": atrium_rows, "hillmount": hillmount_rows}

# Lenders with no machine-readable public rates. They are shown with the reason and never fetched.
NOT_PUBLIC = {
    "ALT01": "blocked: Home Trust's site uses bot protection (Radware); rates go to brokers",
    "ALT03": "broker-only: Haventree sends rate sheets to brokers by email",
    "ALT10": "blocked: MCAN's site uses a browser check; rate sheets are in its broker resources",
    "ALT12": "not published: Merix shows only its prime rate; pricing through brokers",
    "ALT17": "blocked: HomeEquity Bank (CHIP) refuses automated requests",
    "ALT19": "broker-only: Fisgard (now part of Neighbourhood) prices each deal through brokers",
    "ALT21": "broker-only: CMI publishes no current rates",
    "ALT22": "broker-only: Brightpath works only through brokers",
    "ALT25": "not published: Firm Capital quotes prime + spread only in a dated brochure",
    "ALT27": "not published: Alpine Credits shows an example rate only; quotes per application",
    "ALT28": "range only: Fairstone publishes a 14.99%-20.25% range for home-equity loans, not per-term rates",
    "ALT29": "broker-only: Neighbourhood prices by LTV and credit score on request",
}
PDF_PARSERS = {"wealthone_pdf": wealthone_rows}
