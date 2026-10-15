"""Prepayment penalty engine: 3 months' interest, IRD, transition points, forecast, calibration.

Accuracy comes from four inputs (the same four that make paid tools like Prepayment Penalty Mentor exact):
  1. The lender's posted rates on the ORIGINATION date  -> history.py (daily snapshots + Wayback backfill)
  2. The client's actual discount (welcome package / commitment) -> Mortgage.discount; never guess if you have it
  3. The lender's policy (comparison rate, term matching, 3-month basis) -> POLICIES below, calibrated by calibrate()
  4. The lender's CURRENT rate table on the payout date -> history.py latest snapshot

Policies marked verified=False are best-known defaults. Promote one to verified=True only after calibrate()
reproduces a real payout statement or the lender's own calculator to the dollar.
"""
from dataclasses import dataclass, field, replace
from datetime import date
from itertools import product

TERMS = [6, 12, 24, 36, 48, 60, 84, 120]          # months the lender posts rates for


@dataclass(frozen=True)
class Policy:
    lender: str
    comparison: str = "posted_minus_discount"     # posted_minus_discount | posted | offered
    term_match: str = "nearest"                   # nearest | round_down | round_up | interpolate
    tie_break: str = "down"                       # when exactly between two terms
    three_month_basis: str = "contract"           # contract | posted_at_origination
    time_basis: str = "months"                    # months (remaining_months/12) | days (remaining_days/365)
    present_value: bool = False                   # discount the IRD stream at the comparison rate
    privilege_first: bool = False                 # deduct unused annual prepayment privilege before penalty
    privilege_pct: float = 0.0
    min_term: int = 12                            # shortest term used for comparison (some use 6-month)
    bands: tuple = ()                             # term_match="bands": ((min_months, max_months, term_months), ...)
    months_convention: str = "calendar"           # calendar | td (TD calculator: whole months + (days+1)/31)
    verified: bool = False
    source: str = ""


BIG6 = dict(comparison="posted_minus_discount", term_match="nearest")
# Read from TD's own calculator code (ix0.apps.td.com/mortgage-prepayment-calculator/js/td-prepayment.min.js)
TD_BANDS = ((0, 8.999, 6), (9, 17.999, 12), (18, 29.999, 24), (30, 41.999, 36), (42, 53.999, 48),
            (54, 65.999, 60), (66, 77.999, 72), (78, 101.999, 84), (102, 119.999, 120))
MONO = dict(comparison="offered", term_match="nearest")
POLICIES = {p.lender: p for p in [
    Policy("RBC", **BIG6, source="posted-discount; 3mo window ~7 months per CMT 2026-04"),
    Policy("TD", comparison="posted_minus_discount", term_match="bands", bands=TD_BANDS, min_term=6,
           months_convention="td", verified=True,
           source="TD's published calculator code; reproduced to the cent by backtest.py against td-prepayment.min.js"),
    Policy("Scotiabank", **BIG6, source="posted-discount"),
    Policy("BMO", **BIG6, source="posted-discount"),
    Policy("CIBC", **BIG6, three_month_basis="posted_at_origination", source="3mo at initial posted rate per CMT 2025-07"),
    Policy("National Bank", **BIG6, source="posted-discount"),
    Policy("Tangerine", **BIG6), Policy("Simplii", **BIG6), Policy("Desjardins", **BIG6),
    Policy("Laurentian", **BIG6), Policy("Manulife Bank", **BIG6), Policy("ATB", **BIG6),
    Policy("First National", **MONO), Policy("MCAP", **MONO), Policy("RMG", **MONO), Policy("CMLS", **MONO),
    Policy("Merix", **MONO), Policy("Lendwise", **MONO), Policy("Marathon", **MONO), Policy("Strive", **MONO),
    Policy("Equitable Bank", **MONO), Policy("Home Trust", **MONO), Policy("Haventree", **MONO),
    Policy("Bridgewater", **MONO),
    Policy("Credit union (generic)", comparison="offered", term_match="nearest"),
]}


@dataclass
class Mortgage:
    balance: float                 # principal outstanding on payout date
    contract_rate: float           # % e.g. 4.89
    term_months: int               # original term, e.g. 60
    start: date                    # term start / interest adjustment date
    posted_at_origination: dict = field(default_factory=dict)   # {term_months: rate} on start date
    discount: float | None = None  # % off posted (from welcome package). None -> posted[term] - contract
    amort_months: int = 300
    privilege_used_this_year: float = 0.0
    borrower_is_corporation: bool = False
    maturity: date | None = None   # use the exact maturity date when known (overrides start + term)

    def resolved_discount(self):
        if self.discount is not None:
            return self.discount
        if self.term_months in self.posted_at_origination:
            return round(self.posted_at_origination[self.term_months] - self.contract_rate, 4)
        raise ValueError("Need discount or posted_at_origination[term] - get it from history.py or the welcome package")


def months_between(a: date, b: date) -> float:
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.4375


def add_months(d: date, m: int) -> date:
    """Calendar month arithmetic; the day is clamped only to the target month's length (Oct 31 + 1 -> Nov 30)."""
    import calendar
    y, mo = divmod(d.month - 1 + m, 12)
    year, month = d.year + y, mo + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def maturity_of(m) -> date:
    return m.maturity or add_months(m.start, m.term_months)


def _js_round2(x: float) -> float:
    """Half-up cents, like JavaScript Math.round(100*x)/100 (Python's round() is banker's rounding)."""
    import math
    return math.floor(x * 100 + 0.5) / 100


def td_months_remaining(payout: date, maturity: date) -> float:
    """Exact port of TD's calculator: new Date(dy, dm, dd) -> 12*years + months + (day+1)/31 (rounded 2dp).
    JS rolls day 0 back to the last day of the previous month, which this reproduces."""
    from datetime import timedelta
    dy, dm, dd = maturity.year - payout.year, maturity.month - payout.month, maturity.day - payout.day
    y, mo = 1900 + dy + dm // 12, dm % 12
    d = date(y, mo + 1, 1) + timedelta(days=dd - 1)
    return 12 * (d.year - 1900) + (d.month - 1) + _js_round2((d.day + 1) / 31)


def pick_term(remaining: float, policy: Policy, table: dict):
    """Which term's rate the lender compares against. Returns (term, rate) or interpolated."""
    if policy.term_match == "bands":
        # The band decides the term. Never substitute another term: a missing rate is an error, not a guess.
        term = next((t for lo, hi, t in policy.bands if lo <= remaining <= hi), None)
        if term is None:
            term = policy.bands[-1][2] if remaining > policy.bands[-1][1] else \
                max(((lo, t) for lo, _, t in policy.bands if lo <= remaining), default=(0, policy.bands[0][2]))[1]
        if term not in table:
            raise ValueError(f"{policy.lender} rule needs the {term}-month posted rate, which is missing from the rate table")
        return term, table[term]
    terms = sorted(t for t in table if t >= policy.min_term or t == max(table))
    if not terms:
        raise ValueError("empty rate table")
    if remaining <= terms[0]:
        return terms[0], table[terms[0]]
    if remaining >= terms[-1]:
        return terms[-1], table[terms[-1]]
    lo = max(t for t in terms if t <= remaining)
    hi = min(t for t in terms if t >= remaining)
    if lo == hi:
        return lo, table[lo]
    if policy.term_match == "round_down":
        return lo, table[lo]
    if policy.term_match == "round_up":
        return hi, table[hi]
    if policy.term_match == "interpolate":
        w = (remaining - lo) / (hi - lo)
        return round(remaining, 2), table[lo] + w * (table[hi] - table[lo])
    d_lo, d_hi = remaining - lo, hi - remaining
    if abs(d_lo - d_hi) < 1e-9:
        return (lo, table[lo]) if policy.tie_break == "down" else (hi, table[hi])
    return (lo, table[lo]) if d_lo < d_hi else (hi, table[hi])


def penalty(m: Mortgage, policy: Policy, current: dict, payout: date, current_offered: dict | None = None):
    """current: lender's posted table {term_months: rate} on payout date.
    current_offered: lender's discounted/offered table (for comparison='offered')."""
    end = maturity_of(m)
    remaining = max(td_months_remaining(payout, end) if policy.months_convention == "td" else months_between(payout, end), 0.0)
    remaining_days = max((end - payout).days, 0)
    bal = m.balance
    notes = []
    if payout >= end:                       # at or after maturity there is no prepayment charge
        return {"lender": policy.lender, "payout": payout.isoformat(), "remaining_months": 0.0, "compare_term": None,
                "compare_posted": None, "discount": None, "compare_rate": None, "rate_diff": 0.0, "three_month": 0.0,
                "ird": 0.0, "penalty": 0.0, "method": "matured", "ird_minus_3mo": 0.0, "policy_verified": policy.verified,
                "notes": ["Term has matured: no prepayment charge (discharge or administration fees may still apply)."]}
    if policy.privilege_first and policy.privilege_pct:
        free = max(policy.privilege_pct / 100 * bal - m.privilege_used_this_year, 0)
        bal -= free
        notes.append(f"unused prepayment privilege ${free:,.0f} deducted first")

    three_rate = m.contract_rate
    if policy.three_month_basis == "posted_at_origination":
        three_rate = m.posted_at_origination.get(m.term_months, m.contract_rate)
    three = bal * three_rate / 100 * 3 / 12

    table = current_offered if policy.comparison == "offered" and current_offered else current
    term, comp = pick_term(remaining, policy, table)
    disc = m.resolved_discount() if policy.comparison == "posted_minus_discount" else 0.0
    comp_rate = comp - disc if comp - disc >= 0 else comp      # TD: if posted - discount < 0, use posted
    diff = max(m.contract_rate - comp_rate, 0.0)
    years = remaining_days / 365 if policy.time_basis == "days" else remaining / 12
    if policy.present_value and diff > 0:
        r = comp_rate / 100 / 12
        n = int(round(remaining))
        annuity = (1 - (1 + r) ** -n) / r if r > 0 else n
        ird = bal * diff / 100 / 12 * annuity
    else:
        ird = bal * diff / 100 * years

    pen = max(three, ird)
    # Interest Act s.10: term > 5 years and 5+ years elapsed -> max 3 months' interest (individuals)
    if policy.months_convention == "td":
        # TD's calculator controller: term > 5 years and remaining <= 12 * (term_years - 5) -> three months only
        term_y = m.term_months / 12
        long_rule = term_y > 5 and remaining <= 12 * (term_y - 5)
    else:
        long_rule = m.term_months > 60 and months_between(m.start, payout) >= 60
    if long_rule and not m.borrower_is_corporation:
        pen = three
        notes.append("Interest Act s.10 cap applied (3 months' interest after year 5)")
    return {
        "lender": policy.lender, "payout": payout.isoformat(), "remaining_months": round(remaining, 2),
        "compare_term": term, "compare_posted": round(comp, 4), "discount": round(disc, 4),
        "compare_rate": round(comp_rate, 4), "rate_diff": round(diff, 4),
        "three_month": _js_round2(three), "ird": _js_round2(ird), "penalty": _js_round2(pen),
        "method": "IRD" if ird > three else "3-month", "ird_minus_3mo": round(ird - three, 2),
        "policy_verified": policy.verified, "notes": notes,
    }


def balance_after(m: Mortgage, months: int) -> float:
    """Project balance forward with Canadian semi-annual compounding, monthly payments."""
    j = (1 + m.contract_rate / 200) ** (1 / 6) - 1
    n = m.amort_months
    pmt = m.balance * j / (1 - (1 + j) ** -n)
    b = m.balance
    for _ in range(months):
        b = b * (1 + j) - pmt
    return max(b, 0)


def forecast(m: Mortgage, policy: Policy, current: dict, from_date: date, current_offered=None, step_days=7):
    """Penalty path to maturity if today's rate tables hold. Flags TRANSITION POINTS where the compare term changes.
    Stops at the actual maturity date (m.maturity when supplied)."""
    end = maturity_of(m)
    rows, last_term, d, i = [], None, from_date, 0
    while d < end:
        mm = replace(m, balance=balance_after(m, int(months_between(from_date, d))))
        r = penalty(mm, policy, current, d, current_offered)
        r["transition"] = last_term is not None and r["compare_term"] != last_term
        last_term = r["compare_term"]
        rows.append(r)
        i += 1
        d = date.fromordinal(from_date.toordinal() + i * step_days)
    return rows


def calibrate(m: Mortgage, current: dict, payout: date, actual: float, current_offered=None, tol=5.0, lender="?"):
    """Find every policy combination that reproduces a real payout-statement penalty within $tol."""
    hits = []
    for comp, tm, tb, three, tbasis, pv, mt in product(
            ["posted_minus_discount", "posted", "offered"], ["nearest", "round_down", "round_up", "interpolate"],
            ["down", "up"], ["contract", "posted_at_origination"], ["months", "days"], [False, True], [6, 12]):
        if comp == "offered" and not current_offered:
            continue
        p = Policy(lender, comp, tm, tb, three, tbasis, pv, min_term=mt)
        try:
            r = penalty(m, p, current, payout, current_offered)
        except ValueError:
            continue
        if abs(r["penalty"] - actual) <= tol:
            hits.append((abs(r["penalty"] - actual), p, r))
    return sorted(hits, key=lambda h: h[0])
