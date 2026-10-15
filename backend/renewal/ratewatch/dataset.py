"""Five-year rate dataset, built now from official sources plus each bank's own captured rates.

    python -m renewal.ratewatch.dataset      -> data/ratewatch/rates_5yr.csv          (long format, every value sourced)
                                             -> data/ratewatch/big6_posted_5yr.csv    (weekly, one column per bank)

Official (complete, weekly, Bank of Canada Valet - no key):
  CHARTERED_BANK_INTEREST  big-six typical posted 1/3/5-yr + prime
  A4_RATES_MORTGAGES       actual average rate on NEW mortgages, insured/uninsured, by term bucket
  bond_yields_benchmark    Government of Canada 2/3/5/7/10-yr
  V39079                   policy rate
Per bank: only the bank's own data (live feeds, archived pages/feeds). Blank = no capture. Nothing is estimated.
"""
import csv
from datetime import date, timedelta
import requests
from .paths import DATA
from . import history

VALET = "https://www.bankofcanada.ca/valet/observations"
BIG6 = {"P021": "RBC", "P023": "TD", "P025": "Scotiabank", "P027": "BMO", "P029": "CIBC", "P031": "National Bank"}


def _group(name, start):
    js = requests.get(f"{VALET}/group/{name}/json", params={"start_date": start}, timeout=90).json()
    labels = {k: v.get("label", k) for k, v in js.get("seriesDetail", {}).items()}
    return js["observations"], labels


def _term_of(label):
    l = label.lower()
    for key, months in (("1-year", 12), ("3-year", 36), ("5-year", 60), ("2-year", 24), ("7-year", 84), ("10-year", 120),
                        ("<1 year", 6), ("1 to <3", 24), ("3 to <5", 48), ("5 years and over", 60), ("variable", 0)):
        if key in l:
            return months
    return ""


def _a4_series(sid):
    """A4 block layout (from series descriptions): 775-786 funds advanced (new loans), 787-798 outstanding balances;
    within each block the first six are insured, the next six uninsured."""
    try:
        n = int(sid.lstrip("V"))
    except ValueError:
        return None
    if not 122667775 <= n <= 122667798:
        return None
    block = "new" if n <= 122667786 else "outstanding"
    insured = "insured" if (n - 122667775) % 12 < 6 else "uninsured"
    return f"actual_rate_{block}_{insured}"


def build(years=5):
    start = (date.today().replace(day=1) - timedelta(days=365 * years + 2)).isoformat()
    rows = []
    obs, labels = _group("CHARTERED_BANK_INTEREST", start)
    for o in obs:
        for sid in ("V80691333", "V80691334", "V80691335", "V80691311"):
            if o.get(sid, {}).get("v"):
                rows.append([o["d"], "big6_typical_posted" if sid != "V80691311" else "prime", _term_of(labels[sid]) if sid != "V80691311" else "",
                             labels[sid], float(o[sid]["v"]), "Bank of Canada Valet", sid])
    obs, labels = _group("A4_RATES_MORTGAGES", start)
    for o in obs:
        for sid, v in o.items():
            if sid != "d" and v.get("v"):
                lab = labels.get(sid, sid).replace("&lt;", "<")
                series = _a4_series(sid)
                if series:
                    rows.append([o["d"], series, _term_of(lab), lab, float(v["v"]), "Bank of Canada Valet (A4)", sid])
    obs, labels = _group("bond_yields_benchmark", start)
    for o in obs:
        for sid, v in o.items():
            if sid != "d" and v.get("v") and "YLD" in sid:
                rows.append([o["d"], "goc_bond_yield", _term_of(labels.get(sid, sid)), labels.get(sid, sid), float(v["v"]), "Bank of Canada Valet", sid])
    pol = requests.get(f"{VALET}/V39079/json", params={"start_date": start}, timeout=60).json()["observations"]
    rows += [[o["d"], "policy_rate", "", "Target for the overnight rate", float(o["V39079"]["v"]), "Bank of Canada Valet", "V39079"]
             for o in pol if o.get("V39079", {}).get("v")]
    with history.db() as c:
        bank = c.execute("SELECT source, day, term, rtype, rate, how FROM rates WHERE kind='fixed_closed' AND day>=? "
                         "AND source IN (%s) AND rtype IN ('posted','special')" % ",".join("?" * len(BIG6)), (start, *BIG6)).fetchall()
    rows += [[d, f"bank_{rt}", t, BIG6[s], r, f"{BIG6[s]} own data ({how})", s] for s, d, t, rt, r, how in bank]
    rows.sort(key=lambda r: (r[0], r[1], str(r[2])))
    with open(DATA / "rates_5yr.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "series", "term_months", "label", "rate", "source", "source_id"])
        w.writerows(rows)
    wide = _wide(rows)
    conf = history.conflicts(since=start)
    with open(DATA / "rate_conflicts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "day", "term_months", "kind", "type", "method_a", "rate_a", "method_b", "rate_b"])
        w.writerows(conf)
    wide["conflicts"] = len(conf)
    return {"rows": len(rows), "from": rows[0][0] if rows else None, "to": rows[-1][0] if rows else None, **wide}


def _wide(rows):
    """Weekly 5-yr posted: BoC typical + each bank's own value in force that week (blank if none captured)."""
    weeks = sorted({r[0] for r in rows if r[1] == "big6_typical_posted" and r[2] == 60})
    boc = {r[0]: r[4] for r in rows if r[1] == "big6_typical_posted" and r[2] == 60}
    filled = {b: 0 for b in BIG6}
    with open(DATA / "big6_posted_5yr.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["week", "boc_big6_typical_5yr", *[f"{n}_5yr_posted" for n in BIG6.values()], *[f"{n}_captured_on" for n in BIG6.values()]])
        for wk in weeks:
            vals, days = [], []
            for sid in BIG6:
                t, day = history.table_on(sid, date.fromisoformat(wk), max_age_days=35)
                vals.append(t.get(60, ""))
                days.append(day if t.get(60) is not None else "")
                if t.get(60) is not None:
                    filled[sid] += 1
            w.writerow([wk, boc[wk], *vals, *days])
    return {"weeks": len(weeks), "bank_weeks_filled": {BIG6[k]: v for k, v in filled.items()}}


if __name__ == "__main__":
    print(build())
