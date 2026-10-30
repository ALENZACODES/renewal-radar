"""Automatic back-checks. Each rule returns (rule, source, status, detail, fix_from). FAIL rows go to data/alerts.csv.

Rules (cheapest, strongest first):
  R1 range         0.5% < rate < 15%
  R2 posted>=special for the same term
  R3 BoC anchor    big-6 5yr posted within 0.50 of BoC V80691335 (the BoC series IS the most common big-6 posted rate)
  R4 StatCan==BoC  vector 80691335 same value in two government systems (catches API/transport errors)
  R5 bond spread   5yr posted - GoC 5yr yield between 0.5 and 4.5
  R6 jump          day-over-day move > 0.75 needs a second source to agree
  R7 coverage      a lender that had rows yesterday has rows today (silent layout change)
  R8 prime         every big-6 prime equals BoC prime V80691311
  R9 conflict      two collection methods disagree for the same lender/day/term (shown, never merged)
"""
from .paths import DATA as _DATA
import csv
from datetime import date, timedelta
from pathlib import Path
import requests
from .history import db, table_on
from . import history
from .registry import PRIMARY

BIG6 = ["P021", "P023", "P025", "P027", "P029", "P031"]
FIX = {r[0]: r[7] for r in PRIMARY}
OUT = _DATA


def boc_latest(series):
    js = requests.get(f"https://www.bankofcanada.ca/valet/observations/{series}/json?recent=1", timeout=30).json()
    ob = js["observations"][-1]
    return ob["d"], float(ob[series]["v"])


def statcan_latest(vector):
    r = requests.post("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
                      json=[{"vectorId": vector, "latestN": 1}], timeout=30).json()
    p = r[0]["object"]["vectorDataPoint"][-1]
    return p["refPer"], float(p["value"])


def run(today=None):
    today = today or date.today()
    res = []
    add = lambda rule, src, ok, detail: res.append((rule, src, "PASS" if ok else "FAIL", detail, FIX.get(src, "")))

    d_boc, boc5 = boc_latest("V80691335")
    try:
        d_sc, sc5 = statcan_latest(80691335)
        add("R4", "P001", abs(sc5 - boc5) < 1e-9 or d_sc != d_boc, f"BoC {d_boc} {boc5} vs StatCan {d_sc} {sc5}")
    except Exception as e:
        add("R4", "P001", False, f"StatCan unreachable: {e}")
    _, goc5 = boc_latest("BD.CDN.5YR.DQ.YLD")
    _, prime = boc_latest("V80691311")

    with db() as c:
        sources = [r[0] for r in c.execute("SELECT DISTINCT source FROM rates WHERE how IN ('api','html')")]
    for src in sources:
        posted, d = table_on(src, today, "posted", max_age_days=3)
        special, _ = table_on(src, today, "special", max_age_days=3)
        prev, _ = table_on(src, today - timedelta(days=1), "posted", max_age_days=5)
        if not posted and not special:
            add("R7", src, False, "no rows today (layout change, block, or JS) - run discover/scrape")
            continue
        bad = {t: r for t, r in {**posted, **special}.items() if not 0.5 < r < 15}
        add("R1", src, not bad, f"out of range: {bad}" if bad else "ok")
        inv = {t: (posted[t], special[t]) for t in posted if t in special and special[t] > posted[t] + 0.01 and t >= 36}
        add("R2", src, not inv, f"special>posted: {inv}" if inv else "ok")
        if src in BIG6 and 60 in posted:
            add("R3", src, abs(posted[60] - boc5) <= 0.50, f"5yr posted {posted[60]} vs BoC {boc5}")
        if 60 in posted:
            sp = posted[60] - goc5
            add("R5", src, 0.5 <= sp <= 4.5, f"5yr posted-GoC5 spread {sp:.2f}")
        jumps = {t: (prev[t], posted[t]) for t in posted if t in prev and abs(posted[t] - prev[t]) > 0.75}
        add("R6", src, not jumps, f"big move, confirm with 2nd source: {jumps}" if jumps else "ok")
        if src in BIG6:
            pr, _ = table_on(src, today, "posted", kind="prime", max_age_days=3)
            if pr:
                add("R8", src, abs(pr.get(0, prime) - prime) < 0.01, f"prime {pr.get(0)} vs BoC {prime}")

    for src, day, term, kind, rtype, how_a, rate_a, how_b, rate_b in history.conflicts(since=today - timedelta(days=7)):
        add("R9", src, False, f"{day} {term}m {rtype}: {how_a}={rate_a} vs {how_b}={rate_b} (sources disagree)")
    OUT.mkdir(exist_ok=True)
    with open(OUT / "alerts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rule", "source", "status", "detail", "fix_from"])
        w.writerows(r for r in res if r[2] == "FAIL")
    return res
