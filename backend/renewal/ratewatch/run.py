"""Command line.

  python -m renewal.ratewatch.run daily                 snapshot every primary source + BoC, then back-checks
  python -m renewal.ratewatch.run official              load BoC posted/prime/bond history since 2000
  python -m renewal.ratewatch.run backfill P021 2019    Wayback monthly history for one lender
  python -m renewal.ratewatch.run penalty TD 400000 4.89 60 2023-10-15 --posted-orig 6.89 [--discount 2.0] [--payout 2026-10-15]
  python -m renewal.ratewatch.run forecast TD 400000 4.89 60 2023-10-15 --posted-orig 6.89
  python -m renewal.ratewatch.run accuracy              calibrate on data/penalty_cases.csv, print hit rate
  python -m renewal.ratewatch.run linkcheck             health-check all 200 URLs
"""
from .paths import DATA as _DATA
import argparse, sys
from pathlib import Path
from datetime import date
from . import accuracy, history, validate
from .ird import Mortgage, forecast, penalty
from .registry import PRIMARY
from .scrape import fetch

LENDER_SOURCE = {"RBC": "P021", "TD": "P023", "Scotiabank": "P025", "BMO": "P027", "CIBC": "P029",
                 "National Bank": "P031", "Tangerine": "P033", "Simplii": "P034", "Desjardins": "P035",
                 "Laurentian": "P036", "Manulife Bank": "P038", "ATB": "P039"}


def _one(r):
    """Primary fetch; on failure backup 1 (sitemap rediscovery) runs and a working URL is saved (auto-fix)."""
    from .scrape import _overrides, _remember_fix, rediscovered, _get
    from .parse import extract_rates
    url = _overrides().get(r[0], r[4])
    try:
        rows, how = fetch(r[0]) if url == r[4] else (extract_rates(_get(url).text, r[0]), "html")
    except Exception as e:
        rows, how = [], f"error {type(e).__name__}"
    if not rows:
        try:
            rows, new = rediscovered(url)
        except Exception:
            rows, new = [], None
        if rows:
            _remember_fix(r[0], url, new)
            how = f"html AUTO-FIXED -> {new}"
    return r, rows, how


def daily():
    from concurrent.futures import ThreadPoolExecutor
    today = date.today().isoformat()
    ok = fail = fixed = 0
    todo = [r for r in PRIMARY if r[2] not in ("official", "archive") and "policy tracking" not in r[1] and r[5] != "archive"]
    with ThreadPoolExecutor(8) as ex:
        for r, rows, how in ex.map(_one, todo):
            if rows:
                history.save(r[0], today, rows, "api" if how == "api" else "html")
                ok += 1
                if "AUTO-FIXED" in how:
                    fixed += 1
                    print(f"  {r[0]} {r[1]}: {how}")
            else:
                fail += 1
                print(f"  no rates: {r[0]} {r[1]} ({how}) -> fix from {r[7]}")
    history.official(start=str(date.today().replace(year=date.today().year - 1)))
    res = validate.run()
    fails = [x for x in res if x[2] == "FAIL"]
    print(f"scraped {ok} sources with rates ({fixed} auto-fixed today), {fail} without; "
          f"{len(res) - len(fails)} checks passed, {len(fails)} failed")
    for f in fails:
        print("  FAIL", *f[:4], "-> fix from", f[4])


def build_mortgage(a):
    m = Mortgage(a.balance, a.rate, a.term, date.fromisoformat(a.start),
                 {a.term: a.posted_orig} if a.posted_orig else {}, a.discount)
    src = LENDER_SOURCE.get(a.lender)
    if not m.posted_at_origination and m.discount is None and src:
        t, d = history.table_on(src, m.start, max_age_days=45)
        if not t:
            t, d = history.table_on("BIG6_TYPICAL", m.start, max_age_days=10)
            print(f"  origination posted rate from BoC big-6 typical ({d}) - ESTIMATE; use the welcome-package discount")
        m.posted_at_origination = t
    return m, src


def current_tables(src, payout):
    cur, d = history.table_on(src, payout, "posted", max_age_days=7, own_only=True) if src else ({}, None)
    off, _ = history.table_on(src, payout, "special", max_age_days=7, own_only=True) if src else ({}, None)
    if not cur and src:
        rows, _ = fetch(src)
        cur = {t: r for t, k, rt, r in rows if k == "fixed_closed" and rt == "posted"}
        off = {t: r for t, k, rt, r in rows if k == "fixed_closed" and rt == "special"}
    return cur, off or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--posted-orig", type=float)
    ap.add_argument("--discount", type=float)
    ap.add_argument("--payout")
    a = ap.parse_args()
    if a.cmd == "daily":
        return daily()
    if a.cmd == "official":
        return print(history.official(), "days loaded")
    if a.cmd == "backfill":
        return print(history.backfill(a.args[0], int(a.args[1]) if len(a.args) > 1 else 2019))
    if a.cmd == "accuracy":
        return print(accuracy.run())
    if a.cmd == "linkcheck":
        from . import linkcheck
        sys.argv = sys.argv[:1]
        return linkcheck.main()
    if a.cmd in ("penalty", "forecast"):
        a.lender, a.balance, a.rate, a.term, a.start = a.args[0], float(a.args[1]), float(a.args[2]), int(a.args[3]), a.args[4]
        m, src = build_mortgage(a)
        payout = date.fromisoformat(a.payout) if a.payout else date.today()
        cur, off = current_tables(src, payout)
        pol = accuracy.policy_for(a.lender)
        alerts = _DATA / "alerts.csv"
        if src and alerts.exists() and f",{src}," in alerts.read_text(encoding="utf-8"):
            print(f"  WARNING: today's rates for {src} FAILED a back-check (see data/alerts.csv) - result not reliable")
        if a.cmd == "penalty":
            r = penalty(m, pol, cur, payout, off)
            for k, v in r.items():
                print(f"  {k:18} {v}")
            if not pol.verified:
                print("  ESTIMATE: this lender's policy has not passed the 99% gate yet (python -m renewal.ratewatch.run accuracy)")
        else:
            last = None
            for r in forecast(m, pol, cur, payout, off, step_days=7):
                if r["transition"] or last is None or r["method"] != last["method"]:
                    print(f"  {r['payout']}  compare {r['compare_term']:>5}m  penalty ${r['penalty']:>10,.2f}  ({r['method']})"
                          f"{'  <- TRANSITION POINT' if r['transition'] else ''}")
                last = r
            best = min(forecast(m, pol, cur, payout, off, step_days=1), key=lambda r: r["penalty"])
            print(f"  cheapest date if rates hold: {best['payout']} ${best['penalty']:,.2f}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
