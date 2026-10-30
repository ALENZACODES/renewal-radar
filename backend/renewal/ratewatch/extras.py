"""Twelve decision helpers built on the penalty engine. Pure functions; API routes live in api.py.

1 break_even            months of lower payments needed to earn back the penalty
2 cheapest_day          lowest penalty in the next N days (maturity day excluded)
3 blend_and_extend      blended rate a lender would typically offer instead of a penalty
4 lump_sum_first        penalty saved by using the annual prepayment allowance before breaking
5 sensitivity           penalty if the lender's posted rates move by +/-0.25 and +/-0.50
6 port_vs_break         cost of breaking vs porting the mortgage to a new home
7 renewal_countdown     days to maturity and the 120-day early-renewal window
8 stress_test           OSFI qualifying rate (greater of contract + 2% or 5.25%) and payment
9 net_switch_benefit    interest saved over the new term minus penalty and fees
10 to_csv               penalty + forecast as CSV text
11 summary_text         plain-text summary for email or SMS
12 French letter        see letter.build_letter(language="fr")
"""
from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import date, timedelta

from .ird import Mortgage, Policy, add_months, forecast, maturity_of, penalty

OSFI_FLOOR = 5.25
EARLY_RENEWAL_DAYS = 120


def monthly_payment(principal: float, annual_rate: float, months: int) -> float:
    """Canadian fixed mortgage: semi-annual compounding, monthly payments."""
    j = (1 + annual_rate / 200) ** (1 / 6) - 1
    return principal / months if j == 0 else principal * j / (1 - (1 + j) ** -months)


def interest_over(principal: float, annual_rate: float, amort_months: int, months: int) -> float:
    j = (1 + annual_rate / 200) ** (1 / 6) - 1
    pmt, bal, paid = monthly_payment(principal, annual_rate, amort_months), principal, 0.0
    for _ in range(months):
        i = bal * j
        paid += i
        bal = bal + i - pmt
    return paid


def _interest_path(principal, annual_rate, amort_months, months):
    """Interest charged each month on a Canadian fixed mortgage (semi-annual compounding, level payment)."""
    j = (1 + annual_rate / 200) ** (1 / 6) - 1
    pmt, bal, out = monthly_payment(principal, annual_rate, amort_months), principal, []
    for _ in range(months):
        if bal <= 0:
            out.append(0.0)                       # repaid: no further interest (never negative)
            continue
        i = bal * j
        out.append(i)
        bal = max(bal + i - pmt, 0.0)
    return out


def _horizon(remaining_months: float, new_term_months: int | None) -> int:
    """Compare only while BOTH rates are known: the old term's remainder and the new offer's guaranteed term."""
    n = max(int(remaining_months), 1)
    return min(n, new_term_months) if new_term_months else n


def break_even(m: Mortgage, policy: Policy, table: dict, payout: date, new_rate: float, fees: float = 0.0,
               new_term_months: int | None = None) -> dict:
    """Months of INTEREST savings needed to recover penalty + fees. Same basis as net_switch_benefit, so the two
    always agree: worth_it is True exactly when net_switch_benefit over the remaining term is positive."""
    r = penalty(m, policy, table, payout)
    cost = r["penalty"] + fees
    n = _horizon(r["remaining_months"], new_term_months)
    old, new = _interest_path(m.balance, m.contract_rate, m.amort_months, n), _interest_path(m.balance, new_rate, m.amort_months, n)
    cum, months = 0.0, None
    for k, (a, b) in enumerate(zip(old, new), start=1):
        cum += a - b
        if months is None and cum >= cost:
            months = k
    return {"penalty_plus_fees": round(cost, 2), "interest_saved_over_remaining_term": round(cum, 2),
            "first_month_interest_saving": round(old[0] - new[0], 2), "break_even_months": months,
            "worth_it_within_remaining_term": cum - cost > 0, "remaining_months": r["remaining_months"], "horizon_months": n}


def cheapest_day(m: Mortgage, policy: Policy, table: dict, start: date, days: int = 365) -> dict:
    end = maturity_of(m)
    best = None
    for k in range(days):
        d = start + timedelta(days=k)
        if d >= end:
            break
        r = penalty(m, policy, table, d)
        if best is None or r["penalty"] < best["penalty"]:
            best = r
    return {"date": best["payout"], "penalty": best["penalty"], "today": penalty(m, policy, table, start)["penalty"]} if best else {}


def blend_and_extend(m: Mortgage, payout: date, new_rate: float, new_term_months: int, policy: Policy, table: dict) -> dict:
    remaining = penalty(m, policy, table, payout)["remaining_months"]
    blended = (m.contract_rate * remaining + new_rate * (new_term_months - remaining)) / new_term_months if new_term_months > remaining else new_rate
    return {"remaining_months": remaining, "blended_rate": round(blended, 3), "new_term_months": new_term_months,
            "note": "Typical weighted-average blend; lenders may add a premium. Ask for their written blend quote."}


def lump_sum_first(m: Mortgage, policy: Policy, table: dict, payout: date, allowance_pct: float = 15.0,
                   original_amount: float | None = None) -> dict:
    base = penalty(m, policy, table, payout)["penalty"]
    lump = allowance_pct / 100 * (original_amount or m.balance)
    after = penalty(replace(m, balance=max(m.balance - lump, 0)), policy, table, payout)["penalty"]
    return {"penalty_without": base, "lump_sum": round(lump, 2), "penalty_after_lump_sum": after, "saved": round(base - after, 2),
            "note": "Only if your contract lets you use the annual privilege right before paying out - confirm first."}


def sensitivity(m: Mortgage, policy: Policy, table: dict, payout: date, moves=(-0.5, -0.25, 0.0, 0.25, 0.5)) -> list:
    return [{"posted_move": mv, "penalty": penalty(m, policy, {t: r + mv for t, r in table.items()}, payout)["penalty"]} for mv in moves]


def port_vs_break(m: Mortgage, policy: Policy, table: dict, payout: date, port_fee: float = 0.0, blend_premium_rate: float | None = None,
                  extra_borrowing: float = 0.0) -> dict:
    brk = penalty(m, policy, table, payout)["penalty"]
    extra_cost = 0.0
    if blend_premium_rate is not None and extra_borrowing:
        extra_cost = extra_borrowing * max(blend_premium_rate - m.contract_rate, 0) / 100 * penalty(m, policy, table, payout)["remaining_months"] / 12
    port = port_fee + extra_cost
    return {"break_cost": brk, "port_cost": round(port, 2), "cheaper": "port" if port < brk else "break", "difference": round(abs(brk - port), 2)}


def renewal_countdown(m: Mortgage, today: date) -> dict:
    end = maturity_of(m)
    window = end - timedelta(days=EARLY_RENEWAL_DAYS)
    return {"maturity": end.isoformat(), "days_to_maturity": (end - today).days, "early_renewal_window_opens": window.isoformat(),
            "in_window": window <= today <= end}


def stress_test(balance: float, contract_rate: float, amort_months: int = 300) -> dict:
    q = max(contract_rate + 2, OSFI_FLOOR)
    return {"qualifying_rate": round(q, 2), "qualifying_payment": round(monthly_payment(balance, q, amort_months), 2),
            "contract_payment": round(monthly_payment(balance, contract_rate, amort_months), 2),
            "note": "Straight renewals and many insured switches are exempt from the stress test; uninsured switches may need it."}


def net_switch_benefit(m: Mortgage, policy: Policy, table: dict, payout: date, new_rate: float, fees: float = 0.0,
                       horizon_months: int | None = None, new_term_months: int | None = None) -> dict:
    r = penalty(m, policy, table, payout)
    n = horizon_months or _horizon(r["remaining_months"], new_term_months)
    saved = sum(_interest_path(m.balance, m.contract_rate, m.amort_months, n)) - sum(_interest_path(m.balance, new_rate, m.amort_months, n))
    net = saved - r["penalty"] - fees
    return {"horizon_months": n, "interest_saved": round(saved, 2), "penalty": r["penalty"], "fees": fees,
            "net_benefit": round(net, 2), "switch": net > 0}


def reverse_rate(m: Mortgage, policy: Policy, payout: date, quoted_penalty: float, tol: float = 0.5,
                 lo: float = 0.0, hi: float = 15.0) -> dict:
    """Which posted rates (for the term the lender's rule selects) are COMPATIBLE with a quoted penalty?

    Solved exactly instead of by searching. The charge is max(three months' interest, IRD) and the IRD is linear in
    the comparison rate c: IRD = k * max(contract - c, 0). The comparison rate is posted - discount, or posted alone
    when that would be negative (TD), so each target band for c maps to up to two posted-rate intervals. Every
    interval is then checked against the engine itself. Returns all intervals; 'unique' only for exactly one narrow one."""
    terms = (6, 12, 24, 36, 48, 60, 72, 84, 120)
    run = lambda x: penalty(m, policy, {t: x for t in terms}, payout)
    pen = lambda x: run(x)["penalty"]
    probe = run(hi)
    term, three = probe["compare_term"], probe["three_month"]
    if policy.comparison == "posted_minus_discount":
        disc = m.resolved_discount()             # documented discount, or original posted rate - contract rate
    else:
        disc = 0.0
    if any("Interest Act" in n for n in probe.get("notes", [])):
        # Long-term cap: the charge is three months' interest whatever the posted rate is.
        fits = abs(three - quoted_penalty) <= tol
        return {"compare_term": term, "compatible_posted_rate_ranges": [(lo, hi)] if fits else [], "unique": False,
                "assumes": {"discount": disc, "policy": policy.lender, "tolerance_$": tol, "long_term_cap": True},
                "caution": "Long-term cap applies: the posted rate does not affect the charge, so it cannot be inferred."}
    # slope k of IRD per point of comparison rate, measured on the engine (includes the lender's month convention)
    c1, c2 = m.contract_rate - 2.0, m.contract_rate - 1.0
    ird_at = lambda c: run(c + disc)["ird"] if c + disc >= disc else run(c)["ird"]
    k = (ird_at(c1) - ird_at(c2)) / (c2 - c1) if c2 > c1 else 0.0
    bands = []                                   # intervals of comparison rate c that give a fitting charge
    if k > 0:
        lo_c = m.contract_rate - (quoted_penalty + tol) / k
        hi_c = m.contract_rate - (quoted_penalty - tol) / k
        bands.append((lo_c, hi_c))               # IRD within tolerance (only fits when IRD >= three-month)
    if abs(three - quoted_penalty) <= tol:       # three-month interest controls: any c with IRD <= three-month
        bands.append((m.contract_rate - three / k if k > 0 else -1e9, 1e9))
    intervals = []
    for c_lo, c_hi in bands:
        # branch A: posted - discount >= 0  ->  posted = c + disc, needs posted >= disc
        a = (max(c_lo + disc, disc, lo), min(c_hi + disc, hi))
        # branch B: posted - discount < 0   ->  comparison = posted, needs posted < disc
        b = (max(c_lo, lo), min(c_hi, disc - 1e-9, hi))
        for x0, x1 in (a, b):
            if x0 <= x1:
                intervals.append((x0, x1))
    verified = []
    for x0, x1 in sorted(intervals):
        mid = (x0 + x1) / 2
        if abs(pen(mid) - quoted_penalty) <= tol + 0.01:          # cent rounding at the edges
            if verified and x0 <= verified[-1][1] + 1e-6:
                verified[-1] = (verified[-1][0], max(verified[-1][1], x1))
            else:
                verified.append((x0, x1))
    ranges = [(round(a, 5), round(b, 5)) for a, b in verified]
    return {"compare_term": term, "compatible_posted_rate_ranges": ranges,
            "unique": len(ranges) == 1 and ranges[0][1] - ranges[0][0] < 0.01,
            "assumes": {"discount": disc, "policy": policy.lender, "tolerance_$": tol},
            "caution": "Compatible ranges under these assumptions only; another discount, term rule or fee treatment can also fit."}


def heatmap(m: Mortgage, policy: Policy, table: dict, start: date, months_ahead: int = 12,
            moves=(-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)) -> dict:
    """Penalty by settlement month x hypothetical posted-rate move. Also shows interest paid while waiting, because a
    lower penalty later does not mean a lower total cost."""
    from .ird import balance_after
    j = (1 + m.contract_rate / 200) ** (1 / 6) - 1
    grid = []
    for k in range(months_ahead + 1):
        d = add_months(start, k)
        if maturity_of(m) <= d:
            break
        mm = replace(m, balance=balance_after(m, k))
        waiting_interest = sum(balance_after(m, i) * j for i in range(k))
        grid.append({"month": k, "date": d.isoformat(), "balance_assumed": round(mm.balance, 2),
                     "interest_paid_while_waiting": round(waiting_interest, 2),
                     "penalty_by_move": {str(mv): penalty(mm, policy, {t: r + mv for t, r in table.items()}, d)["penalty"] for mv in moves}})
    return {"label": "HYPOTHETICAL: posted rates shifted uniformly; balance follows the regular payment schedule.",
            "moves": list(moves), "rows": grid}


def csv_safe(value) -> str:
    """Neutralize spreadsheet formula injection in CSV cells."""
    if value is None:
        return ''
    s = str(value)
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + s
    return s


def to_csv(result: dict, forecast_rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["field", "value"])
    for k, v in result.items():
        if k != "notes":
            w.writerow([csv_safe(k), csv_safe(v)])
    w.writerow([])
    w.writerow(["date", "compare_term_months", "three_month", "ird", "penalty", "method", "transition"])
    for f in forecast_rows:
        w.writerow([csv_safe(f["payout"]), csv_safe(f["compare_term"]), csv_safe(f["three_month"]),
                    csv_safe(f["ird"]), csv_safe(f["penalty"]), csv_safe(f["method"]), csv_safe(f["transition"])])
    return buf.getvalue()


def summary_text(lender: str, result: dict, cheapest: dict | None = None, language: str = "en") -> str:
    if language == "fr":
        from .letter import _amt
        how = "DTI" if result["method"] == "IRD" else "3 mois d’intérêts"
        s = (f"Renewal Radar : sortir de votre prêt {lender} le {result['payout']} coûterait environ "
             f"{_amt(result['penalty'], 'fr')} ({how}).")
        if cheapest and cheapest.get("penalty", 1e18) < result["penalty"]:
            s += f" Coût le plus bas d’ici un an : {_amt(cheapest['penalty'], 'fr')} le {cheapest['date']}."
        return s + " Estimation; demandez un relevé de remboursement écrit."
    how = "IRD" if result["method"] == "IRD" else "3 months' interest"
    s = (f"Renewal Radar: breaking your {lender} mortgage on {result['payout']} would cost about "
         f"${result['penalty']:,.2f} ({how}).")
    if cheapest and cheapest.get("penalty", 1e18) < result["penalty"]:
        s += f" Lowest cost in the next year: ${cheapest['penalty']:,.2f} on {cheapest['date']}."
    return s + " Estimate only; ask your lender for a written payout statement."
