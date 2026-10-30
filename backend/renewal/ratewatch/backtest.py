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
from .ird import Mortgage, POLICIES, penalty
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
        ours = c.execute(f"SELECT source, day, rate FROM rates WHERE term=60 AND rtype='posted' AND kind='fixed_closed' "
                         f"AND source IN ({','.join('?' * len(big6))})", big6).fetchall()
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
