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
