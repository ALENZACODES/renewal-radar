"""Backtests. python -m renewal.ratewatch.backtest  -> data/ratewatch/backtest_report.json

1. TD ORACLE: TD publishes its prepayment-charge maths as browser JavaScript. tools/td_oracle.mjs runs that
   file unmodified in Node. We generate thousands of random mortgages, run them through TD's own code and
   through our engine, and count exact (to the cent) matches. This is a lender-grade answer key, free.
2. RATE HISTORY vs BANK OF CANADA: the BoC 'conventional 5-year' series is the most common big-6 posted rate
   each week. For every week we hold scraped/archived big-6 posted rates, their most common value must equal
   the BoC number. Also checks TD's own daily posted-rate file (1999-2018) against the BoC.
"""
import collections, json, random, statistics, subprocess
from datetime import date, timedelta
from pathlib import Path
from .paths import DATA, PROJECT_ROOT
from .ird import Mortgage, POLICIES, add_months, penalty
from . import history

TERMS_Y = [0.5, 1, 2, 3, 4, 5, 6, 7, 10]


def _random_case(rng, today):
    table = {t: round(rng.uniform(3.0, 8.5), 2) for t in TERMS_Y}
    term_y = rng.choice([1, 2, 3, 4, 5, 7, 10])
    maturity = today + timedelta(days=rng.randint(1, int(term_y * 365)))
    return {"amount": round(rng.uniform(50_000, 2_000_000), 2), "contract": round(rng.uniform(1.5, 8.0), 2),
            "discount": round(rng.uniform(0, 2.5), 2), "maturity": maturity.isoformat(),
            "term_months": int(term_y * 12), "rates": [{"term": t, "rate": r} for t, r in table.items()]}


def td_oracle(n=2000, seed=2026):
    today = date.today()
    rng = random.Random(seed)
    cases = [_random_case(rng, today) for _ in range(n)]
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / "td_oracle.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    td = json.loads(proc.stdout)
    exact_ird = exact_three = exact_total = within_1 = 0
    misses = []
    for c, t in zip(cases, td):
        mat = date.fromisoformat(c["maturity"])
        table = {int(r["term"] * 12): r["rate"] for r in c["rates"]}
        m = Mortgage(c["amount"], c["contract"], c["term_months"], mat, discount=c["discount"], maturity=mat)
        ours = penalty(m, POLICIES["TD"], table, today)
        td_total = t["final"]
        exact_ird += abs(ours["ird"] - t["ird"]) < 0.005
        exact_three += abs(ours["three_month"] - t["three"]) < 0.005
        ok = abs(ours["penalty"] - td_total) < 0.005
        exact_total += ok
        within_1 += abs(ours["penalty"] - td_total) <= 1.0
        if not ok and len(misses) < 10:
            misses.append({"case": c, "td": t, "ours": {k: ours[k] for k in ("remaining_months", "compare_term", "ird", "three_month")}})
    return {"cases": n, "exact_to_the_cent": exact_total, "exact_rate": round(exact_total / n, 4),
            "ird_exact": exact_ird, "three_month_exact": exact_three, "within_1_dollar": within_1, "examples_of_misses": misses}


def scotia_oracle(n=2000, seed=2027):
    """Random mortgages through Scotiabank's own logic.js (tools/scotia_oracle.mjs) vs our engine."""
    rng = random.Random(seed)
    today = date.today()
    cases = []
    for _ in range(n):
        term = rng.choice([12, 24, 36, 48, 60, 84, 120])
        left = rng.randint(1, term)
        rates = {str(t): round(rng.uniform(3.0, 8.5), 2) for t in (6, 12, 24, 36, 48, 60, 84, 120)}
        bal = round(rng.uniform(50_000, 1_500_000), 2)
        cases.append({"balance": bal, "original": round(bal * rng.uniform(1.0, 1.4), 2),
                      "contract": round(rng.uniform(1.5, 8.0), 2), "discount": round(rng.uniform(0, 2.5), 2),
                      "months_remaining": left, "term_months": term, "rates": rates})
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / "scotia_oracle.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    scotia = json.loads(proc.stdout)
    exact = within_1 = 0
    misses = []
    for c, sres in zip(cases, scotia):
        mat = add_months(today, c["months_remaining"])
        m = Mortgage(c["balance"], c["contract"], c["term_months"], mat, discount=c["discount"], maturity=mat)
        table = {int(k): v for k, v in c["rates"].items()}
        ours = penalty(m, POLICIES["Scotiabank"], table, today)
        ok = abs(ours["penalty"] - sres["charge"]) < 0.005
        exact += ok
        within_1 += abs(ours["penalty"] - sres["charge"]) <= 1.0
        if not ok and len(misses) < 10:
            misses.append({"case": c, "scotia": sres, "ours": ours["penalty"], "remaining": ours["remaining_months"]})
    return {"cases": n, "exact_to_the_cent": exact, "exact_rate": round(exact / n, 4), "within_1_dollar": within_1,
            "examples_of_misses": misses}


def cibc_oracle(n=2000, seed=2028):
    """Random mortgages through CIBC's own mortgageprepayment.min.js (tools/cibc_oracle.mjs) vs our engine."""
    import os
    from .ird import monthly_payment
    rng = random.Random(seed)
    today = date.today()
    cases = []
    for _ in range(n):
        mat = today + timedelta(days=rng.randint(1, 60 * 31))
        bal = round(rng.uniform(50_000, 1_500_000), 2)
        contract = round(rng.uniform(1.5, 8.0), 2)
        pay = round(monthly_payment(bal, contract, rng.choice([180, 240, 300, 360])), 2)
        cases.append({"balance": bal, "payment": pay, "contract": contract, "discount": round(rng.uniform(0, 2.5), 2),
                      "today": today.isoformat(), "maturity": mat.isoformat(),
                      "rates": {str(t): round(rng.uniform(3.0, 8.5), 2) for t in (6, 12, 24, 36, 48, 60, 84, 120)}})
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / "cibc_oracle.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=600, env={**os.environ, "TZ": "UTC"})
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    cibc = json.loads(proc.stdout)
    exact = within_1 = 0
    misses = []
    for c, r in zip(cases, cibc):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=c["discount"], maturity=mat, payment=c["payment"])
        ours = penalty(m, POLICIES["CIBC"], {int(k): v for k, v in c["rates"].items()}, today)
        ok = abs(ours["penalty"] - r["charge"]) < 0.005
        exact += ok
        within_1 += abs(ours["penalty"] - r["charge"]) <= 1.0
        if not ok and len(misses) < 10:
            misses.append({"case": c, "cibc": r, "ours": {k: ours[k] for k in ("penalty", "method", "ird", "three_month")}})
    return {"cases": n, "exact_to_the_cent": exact, "exact_rate": round(exact / n, 4), "within_1_dollar": within_1,
            "examples_of_misses": misses}


def bmo_oracle(n=2000, seed=2029):
    """Random mortgages through BMO's own calculator code (tools/bmo_oracle.mjs) vs our engine."""
    rng = random.Random(seed)
    today = date.today()
    cases = []
    for _ in range(n):
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 8.0), 2),
                      "discount": round(rng.uniform(0, 2.5), 2), "months": rng.randint(1, 60),
                      "rates": {str(t): round(rng.uniform(3.0, 8.5), 2) for t in (6, 12, 24, 36, 48, 60, 72, 84, 120)}})
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / "bmo_oracle.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    bmo = json.loads(proc.stdout)
    exact = within_1 = 0
    misses = []
    for c, r in zip(cases, bmo):
        mat = add_months(today, c["months"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=c["discount"], maturity=mat)
        ours = penalty(m, POLICIES["BMO"], {int(k): v for k, v in c["rates"].items()}, today)
        ok = abs(ours["penalty"] - r["charge"]) < 0.005
        exact += ok
        within_1 += abs(ours["penalty"] - r["charge"]) <= 1.0
        if not ok and len(misses) < 10:
            misses.append({"case": c, "bmo": r, "ours": {k: ours[k] for k in ("penalty", "compare_posted", "remaining_months")}})
    return {"cases": n, "exact_to_the_cent": exact, "exact_rate": round(exact / n, 4), "within_1_dollar": within_1,
            "examples_of_misses": misses}


def nbc_oracle(n=2000, seed=2030):
    """Random mortgages through National Bank's own calculator script (tools/nbc_oracle.mjs) vs our engine."""
    rng = random.Random(seed)
    today = date.today()
    cases = []
    for _ in range(n):
        months = rng.randint(1, 60)
        rates = {t: round(rng.uniform(3.0, 8.5), 2) for t in (6, 12, 24, 36, 48, 60, 84, 120)}
        cases.append({"balance": round(rng.uniform(20_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 8.0), 2),
                      "months": months, "rates": rates})
    for c in cases:                       # the form takes the posted rate the bank's term rule selects
        mat = add_months(today, c["months"])
        c["posted"] = penalty(Mortgage(c["balance"], c["contract"], 60, mat, maturity=mat), POLICIES["National Bank"],
                              c["rates"], today)["compare_posted"]
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / "nbc_oracle.mjs")],
                          input=json.dumps([{k: c[k] for k in ("balance", "contract", "posted", "months")} for c in cases]),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    nbc = json.loads(proc.stdout)
    exact = within_1 = 0
    misses = []
    for c, r in zip(cases, nbc):
        mat = add_months(today, c["months"])
        ours = penalty(Mortgage(c["balance"], c["contract"], 60, mat, maturity=mat), POLICIES["National Bank"], c["rates"], today)
        ok = abs(ours["penalty"] - r["charge"]) < 0.005
        exact += ok
        within_1 += abs(ours["penalty"] - r["charge"]) <= 1.0
        if not ok and len(misses) < 10:
            misses.append({"case": c, "nbc": r, "ours": ours["penalty"]})
    return {"cases": n, "exact_to_the_cent": exact, "exact_rate": round(exact / n, 4), "within_1_dollar": within_1,
            "examples_of_misses": misses}


def td_history_vs_boc():
    """TD's own daily posted 5-year (1999-2018) vs BoC weekly big-6 typical."""
    f = DATA / "td_oracle" / "previous_rates.txt"
    if not f.exists():
        return {"skipped": "td_oracle/previous_rates.txt missing"}
    td = {}
    for line in f.read_text(encoding="utf-16").splitlines()[1:]:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) == 4 and parts[0] == "60":
            td[parts[3]] = float(parts[2])
    with history.db() as c:
        boc = dict(c.execute("SELECT day, rate FROM rates WHERE source='BIG6_TYPICAL' AND term=60 AND rtype='posted'"))
    both = [(d, td[d], boc[d]) for d in boc if d in td]
    if not both:
        return {"weeks_compared": 0, "note": "load BoC history first (python -m renewal.ratewatch.run official)"}
    same = sum(abs(a - b) < 0.005 for _, a, b in both)
    return {"weeks_compared": len(both), "td_equals_boc_typical": same, "share": round(same / len(both), 4),
            "mean_abs_gap": round(statistics.mean(abs(a - b) for _, a, b in both), 4)}


def scraped_vs_boc():
    """Most common big-6 5yr posted (our scraped + archived data) vs BoC, week by week."""
    big6 = ("P021", "P023", "P025", "P027", "P029", "P031")
    with history.db() as c:
        boc = dict(c.execute("SELECT day, rate FROM rates WHERE source='BIG6_TYPICAL' AND term=60 AND rtype='posted'"))
        placeholders = ",".join("?" * len(big6))
        ours = c.execute(
            f"SELECT source, day, rate FROM rates WHERE term=60 AND rtype='posted' AND kind='fixed_closed' "  # nosec B608
            f"AND source IN ({placeholders})",
            big6,
        ).fetchall()
    weekly = collections.defaultdict(dict)
    for src, day, rate in sorted(ours, key=lambda r: r[1]):               # oldest first: latest valid one wins
        d = date.fromisoformat(day)
        wk = (d + timedelta(days=(2 - d.weekday()) % 7)).isoformat()      # the BoC Wednesday ON or AFTER d
        weekly[wk][src] = rate                                            # never an observation from after wk
    rows = []
    for wk, by_bank in weekly.items():
        if wk in boc and len(by_bank) >= 3:
            mode = collections.Counter(by_bank.values()).most_common(1)[0][0]
            rows.append((wk, mode, boc[wk], len(by_bank)))
    same = sum(abs(m - b) < 0.005 for _, m, b, _ in rows)
    return {"weeks_with_3plus_banks": len(rows), "mode_equals_boc": same,
            "share": round(same / len(rows), 4) if rows else None,
            "per_bank_rows": collections.Counter(s for s, _, _ in ours)}


def main():
    report = {"run": date.today().isoformat(), "td_oracle": td_oracle(), "td_history_vs_boc": td_history_vs_boc(),
              "scraped_vs_boc": scraped_vs_boc()}
    (DATA / "backtest_report.json").write_text(json.dumps(report, indent=2, default=str))
    o = report["td_oracle"]
    print(f"TD oracle: {o['exact_to_the_cent']}/{o['cases']} exact to the cent ({o['exact_rate']:.2%}), "
          f"{o['within_1_dollar']} within $1")
    print("TD history vs BoC:", report["td_history_vs_boc"])
    print("Scraped big-6 vs BoC:", {k: v for k, v in report["scraped_vs_boc"].items() if k != "per_bank_rows"})
    return report


if __name__ == "__main__":
    main()
