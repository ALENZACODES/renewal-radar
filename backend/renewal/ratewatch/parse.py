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
