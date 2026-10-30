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
from .ird import TERMS, Mortgage, POLICIES, add_months, penalty
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


def rbc_cases(path=None):
    """Our RBC engine vs answers recorded from RBC's own online Mortgage Prepayment Charge Calculator
    (tools/rbc_oracle.py, server-side, so its answers are saved as a fixture rather than re-run)."""
    from datetime import datetime
    path = path or PROJECT_ROOT / "tests" / "fixtures" / "rbc_calculator_2026-10-18.json"
    cases = json.loads(Path(path).read_text())
    exact = within_30c = 0
    worst, misses = 0.0, []
    for c in cases:
        today = date.fromisoformat(c["today"])
        mat = datetime.strptime(c["maturity"], "%d/%m/%Y").date()
        m = Mortgage(c["balance"], c["rate"], 60, mat, discount=c["discount"], maturity=mat, payment=c["payment"])
        ours = penalty(m, POLICIES["RBC"], {int(k): v for k, v in c["posted"].items()}, today)["penalty"]
        err = round(ours - c["rbc_charge"], 2)
        exact += abs(err) < 0.005
        within_30c += abs(err) <= 0.30
        worst = max(worst, abs(err))
        if abs(err) >= 0.005 and len(misses) < 10:
            misses.append({"maturity": c["maturity"], "rbc": c["rbc_charge"], "ours": ours, "error": err})
    return {"cases": len(cases), "exact_to_the_cent": exact, "within_30_cents": within_30c, "worst_error": worst,
            "examples_of_misses": misses}


def first_national_cases(path=None):
    """Our First National engine vs answers recorded from First National's own online prepayment
    calculator (tools/record_first_national.py drives its RemainingBalanceFixed service; the
    calculator computes server-side, so its answers are saved as a fixture rather than re-run)."""
    path = path or PROJECT_ROOT / "tests" / "fixtures" / "first_national_calculator_2026-10-28.json"
    blob = json.loads(Path(path).read_text())
    cases = blob["cases"] if isinstance(blob, dict) else blob
    exact = within_1 = 0
    worst, misses = 0.0, []
    for c in cases:
        payout = date.fromisoformat(c["payout"])
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], c["term_months"], add_months(mat, -c["term_months"]),
                     discount=0.0, maturity=mat, payment=c["payment"])
        ours = penalty(m, POLICIES["First National"], {t: c["posted"] for t in TERMS}, payout)["penalty"]
        err = round(ours - c["fn_charge"], 2)
        exact += abs(err) < 0.005
        within_1 += abs(err) <= 1.0
        worst = max(worst, abs(err))
        if abs(err) >= 0.005 and len(misses) < 10:
            misses.append({"case": c, "ours": ours, "error": err})
    return {"cases": len(cases), "exact_to_the_cent": exact,
            "exact_rate": round(exact / max(len(cases), 1), 4), "within_1_dollar": within_1,
            "worst_error": worst, "examples_of_misses": misses}


def community_trust_oracle(n=2000, seed=2059):
    """Random fixed mortgages through Community Trust's own calculator code
    (tools/community_trust_oracle.mjs, transcribing the lender's published
    MortgagePrePaymentPenaltyCalculatorPage) vs our engine. The posted-rate table is read
    from the lender's fetched calculator page — the same table the harness uses."""
    import re as _re
    page = (DATA / "community_trust_oracle" / "page.html").read_text()
    table = {int(years) * 12: float(_re.search(rf"rate_{years}\s*=\s*([0-9.]+)", page).group(1))
             for years in range(1, 6)}
    rng, today = random.Random(seed), date(2026, 10, 28)
    cases = [{"balance": round(rng.uniform(50_000, 1_500_000), 2),
              "contract": round(rng.uniform(1.5, 8.5), 2),
              "months": rng.randint(3, 78)} for _ in range(n)]
    answers = _node_oracle("community_trust_oracle.mjs", cases)

    def ours(c):
        mat = add_months(today, c["months"])
        m = Mortgage(c["balance"], c["contract"], 60, add_months(today, -24),
                     discount=0.0, maturity=mat)
        return penalty(m, POLICIES["Community Trust"], table, today)["penalty"]
    return _score(cases, answers, ours)


def _ppcalc_cases(lender, fixture_name):
    """Our engine vs answers recorded from the lender's own vendor-hosted prepayment calculator
    (tools/record_mcap.py; the calculator computes server-side, so its answers are saved as a
    fixture rather than re-run). A case counts exact only when BOTH the charge and the printed
    reinvestment rate match — the rate match is what pins the term-band rule, since a wrong
    band is invisible in the charge whenever the 3-month amount dominates."""
    path = PROJECT_ROOT / "tests" / "fixtures" / fixture_name
    blob = json.loads(Path(path).read_text())
    table = {int(k): v for k, v in blob["reinvestment_table"].items()}
    payout = date(2026, 10, 28)
    exact = rate_exact = within_1 = 0
    worst, misses = 0.0, []
    for c in blob["cases"]:
        mat = add_months(payout, c["rem_months"])
        m = Mortgage(c["balance"], c["contract"], 60, add_months(payout, -24),
                     discount=0.0, maturity=mat, payment=c["payment"])
        r = penalty(m, POLICIES[lender], table, payout)
        err = round(r["penalty"] - c["charge"], 2)
        rate_ok = abs(r["compare_rate"] - c["reinvestment"]) < 0.005
        rate_exact += rate_ok
        exact += abs(err) < 0.005 and rate_ok
        within_1 += abs(err) <= 1.0
        worst = max(worst, abs(err))
        if (abs(err) >= 0.005 or not rate_ok) and len(misses) < 10:
            misses.append({"case": c, "ours": r["penalty"], "our_rate": r["compare_rate"], "error": err})
    n = len(blob["cases"])
    return {"cases": n, "exact_to_the_cent": exact, "exact_rate": round(exact / max(n, 1), 4),
            "reinvestment_rate_matches": rate_exact, "within_1_dollar": within_1,
            "worst_error": worst, "examples_of_misses": misses}


def mcap_cases():
    """MCAP vs its own published prepayment calculator (recorded fixture)."""
    return _ppcalc_cases("MCAP", "mcap_calculator_2026-10-28.json")


def rmg_cases():
    """RMG vs its own published prepayment calculator (recorded fixture)."""
    return _ppcalc_cases("RMG", "rmg_calculator_2026-10-28.json")


def _node_oracle(tool, cases, env=None):
    import os
    proc = subprocess.run(["node", str(PROJECT_ROOT / "tools" / tool)], input=json.dumps(cases), capture_output=True,
                          text=True, timeout=600, env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return json.loads(proc.stdout)


def _score(cases, answers, ours_fn):
    exact, misses = 0, []
    for c, a in zip(cases, answers):
        ours = ours_fn(c)
        ok = abs(ours - a["charge"]) < 0.005
        exact += ok
        if not ok and len(misses) < 10:
            misses.append({"case": c, "lender": a, "ours": ours})
    return {"cases": len(cases), "exact_to_the_cent": exact, "exact_rate": round(exact / max(len(cases), 1), 4),
            "examples_of_misses": misses}


def desjardins_oracle(n=2000, seed=2031):
    """Random mortgages through Desjardins' own calculator code (tools/desjardins_oracle.mjs) vs our engine."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        term = rng.choice([12, 24, 36, 48, 60])
        mat = today + timedelta(days=rng.randint(1, term * 30))
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 8.0), 2),
                      "discount": round(rng.uniform(0, 2.5), 2), "term_months": term, "today": today.isoformat(),
                      "maturity": mat.isoformat(),
                      "rates": {str(t): round(rng.uniform(3.0, 8.5), 2) for t in (12, 24, 36, 48, 60, 72, 84, 120)}})
    answers = _node_oracle("desjardins_oracle.mjs", cases, {"TZ": "UTC"})

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], c["term_months"], mat, discount=c["discount"], maturity=mat)
        return penalty(m, POLICIES["Desjardins"], {int(k): v for k, v in c["rates"].items()}, today)["penalty"]
    return _score(cases, answers, ours)


def tangerine_oracle(n=2000, seed=2032):
    """Random mortgages through Tangerine's own calculator script in a minimal page (tools/tangerine_oracle.mjs)."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        term_y = rng.choice([1, 2, 3, 4, 5, 7, 10])
        k = rng.randint(1, term_y * 12 - 1)          # 0 left = matured: no charge (the form still shows 3 months)
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 8.0), 2),
                      "years": k // 12, "months": k % 12, "term_years": term_y, "frequency": 12,
                      "rates": {str(y): round(rng.uniform(3.0, 8.5), 2) for y in (1, 2, 3, 4, 5, 7, 10)}})
    answers = _node_oracle("tangerine_oracle.mjs", cases)

    def ours(c):
        mat = add_months(today, 12 * c["years"] + c["months"])
        m = Mortgage(c["balance"], c["contract"], c["term_years"] * 12, mat, discount=0.0, maturity=mat)
        return penalty(m, POLICIES["Tangerine"], {int(y) * 12: v for y, v in c["rates"].items()}, today)["penalty"]
    return _score(cases, answers, ours)


def simplii_oracle(n=2000, seed=2033):
    """Random mortgages through Simplii's own calculator modules (tools/simplii_oracle.mjs) vs our engine."""
    from .ird import monthly_payment
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        mat = today + timedelta(days=rng.randint(1, 60 * 31))
        bal, contract = round(rng.uniform(50_000, 1_500_000), 2), round(rng.uniform(1.5, 8.0), 2)
        cases.append({"balance": bal, "payment": round(monthly_payment(bal, contract, rng.choice([180, 240, 300, 360])), 2),
                      "contract": contract, "discount": round(rng.uniform(0, 2.5), 2), "today": today.isoformat(),
                      "maturity": mat.isoformat(),
                      "rates": {str(t): round(rng.uniform(3.0, 8.5), 2) for t in (6, 12, 24, 36, 48, 60, 84, 120)}})
    answers = _node_oracle("simplii_oracle.mjs", cases, {"TZ": "UTC"})

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=c["discount"], maturity=mat, payment=c["payment"])
        return penalty(m, POLICIES["Simplii"], {int(k): v for k, v in c["rates"].items()}, today)["penalty"]
    return _score(cases, answers, ours)


def atb_oracle(n=2000, seed=2034):
    """Random conventional fixed mortgages through ATB's own calculator app (tools/atb_oracle.mjs) vs our engine."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        start = today - timedelta(days=rng.randint(30, 9 * 365))
        mat = today + timedelta(days=rng.randint(10, 5 * 365))
        contract = round(rng.uniform(1.5, 8.0), 2)
        terms = {12: 0, 24: 0, 30: 0, 36: 0, 48: 0, 60: 0}
        rows = []
        for t in terms:
            r = round(rng.uniform(3.0, 8.5), 2)
            terms[t] = r
            rows.append({"Type": "Posted Rates", "Class": "Fixed", "TermYears": str(t / 12).rstrip("0").rstrip("."),
                         "Rate": f"{r:.2f}", "IsHighRatio": False, "IsConventional": True})
        rows.append({"Type": "Posted Rates", "Class": "Fixed", "TermYears": "1", "Rate": "10.35",
                     "IsHighRatio": False, "IsConventional": False})          # open rate: not conventional, ignored
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": contract,
                      "posted_original": round(contract + rng.uniform(0, 2.5), 2), "start": start.isoformat(),
                      "maturity": mat.isoformat(), "prepayment": today.isoformat(), "rates": rows, "_table": terms})
    answers = _node_oracle("atb_oracle.mjs", [{k: v for k, v in c.items() if k != "_table"} for c in cases])

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], 60, date.fromisoformat(c["start"]),
                     discount=round(c["posted_original"] - c["contract"], 4), maturity=mat)
        return penalty(m, POLICIES["ATB"], c["_table"], today)["penalty"]
    return _score(cases, answers, ours)


def haventree_oracle(n=2000, seed=2035):
    """Random mortgages through Haventree's own calculator code (tools/haventree_oracle.mjs) vs our engine."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        k = rng.randint(1, 60)
        rates = [round(rng.uniform(2.5, 7.5), 2) for _ in range(4)]
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 9.0), 2),
                      "years": k // 12, "months": k % 12,
                      "reinvestmentRates": [{"minMonths": 1, "maxMonths": 17, "rate": rates[0]},
                                            {"minMonths": 18, "maxMonths": 29, "rate": rates[1]},
                                            {"minMonths": 30, "maxMonths": 41, "rate": rates[2]},
                                            {"minMonths": 42, "maxMonths": None, "rate": rates[3]}]})
    answers = _node_oracle("haventree_oracle.mjs", cases)

    def ours(c):
        mat = add_months(today, 12 * c["years"] + c["months"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=0.0, maturity=mat)
        table = dict(zip((12, 24, 36, 48), (r["rate"] for r in c["reinvestmentRates"])))
        return penalty(m, POLICIES["Haventree"], table, today)["penalty"]
    return _score(cases, answers, ours)


LAURENTIAN_KEYS = {6: "sixMonths", 12: "oneYear", 24: "twoYears", 36: "threeYears", 48: "fourYears", 60: "fiveYears",
                   72: "sixYears", 84: "sevenYears", 96: "eightYears", 108: "nineYears", 120: "tenYears"}


def laurentian_oracle(n=2000, seed=2036):
    """Random mortgages through Laurentian's own calculator computation (tools/laurentian_oracle.mjs) vs our engine."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        mat = today + timedelta(days=rng.randint(1, 119 * 30))
        contract = round(rng.uniform(1.5, 8.0), 2)
        ref = {t: round(rng.uniform(3.0, 8.5), 2) for t in LAURENTIAN_KEYS}
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": contract,
                      "posted": round(contract + rng.uniform(0, 2.5), 2), "frequency": 0, "today": today.isoformat(),
                      "maturity": mat.isoformat(), "reference": {LAURENTIAN_KEYS[t]: r for t, r in ref.items()}, "_ref": ref})
    answers = _node_oracle("laurentian_oracle.mjs", [{k: v for k, v in c.items() if k != "_ref"} for c in cases], {"TZ": "UTC"})

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=round(c["posted"] - c["contract"], 4), maturity=mat)
        return penalty(m, POLICIES["Laurentian"], c["_ref"], today)["penalty"]
    return _score(cases, answers, ours)


def equitable_oracle(n=2000, seed=2037):
    """Random standard fixed mortgages through Equitable's own calculator code (tools/equitable_oracle.mjs)."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        if rng.random() < 0.1:                                 # exercise the exactly-two-years-to-the-day rule
            mat = date(today.year + 2, today.month, min(today.day, 28))
        else:
            mat = today + timedelta(days=rng.randint(15, 60 * 31))
        yields = {k: round(rng.uniform(1.0, 5.0), 3) for k in ("tBill", "bond24", "bond36", "bond60")}
        cases.append({"balance": round(rng.uniform(50_000, 1_500_000), 2), "contract": round(rng.uniform(1.5, 8.5), 2),
                      "discount": 0, "type": "standardFixed", "today": today.isoformat(), "maturity": mat.isoformat(),
                      "reference": {"standardFixed": yields}})
    answers = _node_oracle("equitable_oracle.mjs", cases)

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["contract"], 60, mat, discount=0.0, maturity=mat)
        y = c["reference"]["standardFixed"]
        return penalty(m, POLICIES["Equitable Bank"], {12: y["tBill"], 24: y["bond24"], 36: y["bond36"], 60: y["bond60"]},
                       today)["penalty"]
    return _score(cases, answers, ours)


def bridgewater_oracle(n=2000, seed=2038):
    """Random full prepayments through Bridgewater's own IRD calculator component (tools/bridgewater_oracle.mjs)."""
    rng, today = random.Random(seed), date.today()
    cases = []
    for _ in range(n):
        term_id = rng.choice([2, 3, 4, 5, 6, 7, 8])
        term_m = {2: 12, 3: 24, 4: 36, 5: 48, 6: 60, 7: 84, 8: 120}[term_id]
        start = today - timedelta(days=rng.randint(1, term_m * 30 - 1)) if rng.random() < 0.9 else date(2010, rng.randint(1, 12), 15)
        mat = today + timedelta(days=rng.randint(10, term_m * 30))
        principal = round(rng.uniform(80_000, 1_600_000), 2)
        cases.append({"principal": principal, "lump_sum": round(rng.uniform(0, principal * 0.1), 2) if rng.random() < 0.3 else 0,
                      "balance": round(principal * rng.uniform(0.5, 1.0), 2), "rate": round(rng.uniform(1.5, 9.0), 2),
                      "term_id": term_id, "term_months": term_m, "start": start.isoformat(), "maturity": mat.isoformat(),
                      "today": today.isoformat(), "bonds": [round(rng.uniform(1.0, 5.0), 4) for _ in range(5)]})
    answers = _node_oracle("bridgewater_oracle.mjs", cases, {"TZ": "UTC"})

    def ours(c):
        mat = date.fromisoformat(c["maturity"])
        m = Mortgage(c["balance"], c["rate"], c["term_months"], date.fromisoformat(c["start"]), discount=0.0, maturity=mat,
                     original_amount=c["principal"], privilege_used_this_year=c["lump_sum"])
        return penalty(m, POLICIES["Bridgewater"], dict(zip((12, 24, 36, 48, 60), c["bonds"])), today)["penalty"]
    return _score(cases, answers, ours)


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
