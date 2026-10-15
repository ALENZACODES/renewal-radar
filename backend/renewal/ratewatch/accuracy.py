"""The 99% gate. A lender's penalties are only labelled ACCURATE after its policy reproduces real quotes.

Feed it real numbers in data/penalty_cases.csv - one row per payout statement or lender-calculator quote:
  lender, balance, contract_rate, term_months, start, payout, discount, posted_orig_term_rate,
  current_table (e.g. "12:5.49;24:5.29;36:6.05;48:5.99;60:6.09"), offered_table (optional), actual_penalty, source
Leave current_table blank to pull it from the history DB for that lender on the payout date.

  python -m renewal.ratewatch.run accuracy
    1. calibrate(): per lender, find the policy that matches the MOST cases within 1%
    2. report hit-rate within 1% and within $50
    3. write data/calibrated_policies.json; lenders at >=99% with >=10 cases become verified=True
"""
from .paths import DATA as _DATA
import csv, json
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from itertools import product
from pathlib import Path
from .ird import Mortgage, Policy, POLICIES, penalty

DATA = _DATA
CASES = DATA / "penalty_cases.csv"
CAL = DATA / "calibrated_policies.json"
HEADER = ["lender", "balance", "contract_rate", "term_months", "start", "payout", "discount",
          "posted_orig_term_rate", "current_table", "offered_table", "actual_penalty", "source", "evidence_kind"]
# Only these count toward verification. Anything else (blank, "synthetic", "example", "estimate") is ignored.
EVIDENCE_KINDS = {"payout_statement", "lender_calculator"}
MIN_HOLDOUT = 10


def _table(s):
    return {int(k): float(v) for k, v in (p.split(":") for p in s.split(";") if p)} if s else {}


def _history_table(lender, day):
    """Posted rates the lender had in force on `day`, from recorded history (never today's rates)."""
    from . import history
    from .api import SOURCES
    sid = SOURCES.get(lender.strip().lower())
    return history.table_on(sid, day, max_age_days=10)[0] if sid else {}


def _case_key(r):
    """Numeric identity of a case: '400000', '400000.00' and '4e5' are the same statement."""
    from decimal import Decimal, InvalidOperation

    def num(v):
        try:
            return str(Decimal(str(v).strip()).normalize()) if str(v).strip() else ""
        except InvalidOperation:
            return str(v).strip().lower()
    tables = tuple(tuple(sorted((int(k), num(v)) for k, v in _table(r.get(c) or "").items())) for c in ("current_table", "offered_table"))
    return ((r.get("lender") or "").strip().lower(), num(r.get("balance")), num(r.get("contract_rate")),
            num(r.get("term_months")), (r.get("start") or "").strip(), (r.get("payout") or "").strip(),
            num(r.get("discount")), num(r.get("posted_orig_term_rate")), tables, num(r.get("actual_penalty")))


def load_cases():
    if not CASES.exists():
        with open(CASES, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADER)
        return []
    out, seen = [], set()
    with open(CASES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("evidence_kind") or "").strip().lower() not in EVIDENCE_KINDS or not (r.get("source") or "").strip():
                continue                                         # no real evidence -> never counts
            key = _case_key(r)
            if key in seen:
                continue                                         # duplicates count once
            seen.add(key)
            m = Mortgage(float(r["balance"]), float(r["contract_rate"]), int(r["term_months"]),
                         date.fromisoformat(r["start"]),
                         {int(r["term_months"]): float(r["posted_orig_term_rate"])} if r["posted_orig_term_rate"] else {},
                         float(r["discount"]) if r["discount"] else None)
            payout = date.fromisoformat(r["payout"])
            current = _table(r["current_table"]) or _history_table(r["lender"], payout)
            if not current:
                continue                                         # no rates for that date: cannot be scored
            out.append((r["lender"], m, payout, current,
                        _table(r["offered_table"]) or None, float(r["actual_penalty"]), r["source"]))
    return out


def grid(lender):
    for comp, tm, tb, three, tbasis, pv, mt in product(
            ["posted_minus_discount", "posted", "offered"], ["nearest", "round_down", "round_up", "interpolate"],
            ["down", "up"], ["contract", "posted_at_origination"], ["months", "days"], [False, True], [6, 12]):
        yield Policy(lender, comp, tm, tb, three, tbasis, pv, min_term=mt)


def score(policy, cases):
    hits1 = hits50 = 0
    errs = []
    for _, m, payout, cur, off, actual, _ in cases:
        try:
            got = penalty(m, policy, cur, payout, off)["penalty"]
        except (ValueError, KeyError):
            errs.append(None)
            continue
        e = got - actual
        errs.append(e)
        hits1 += abs(e) <= 0.01 * actual
        hits50 += abs(e) <= 50
    return hits1, hits50, errs


def _split(cases):
    """Deterministic development / untouched evaluation split (70/30) by a hash of each case."""
    import hashlib
    dev, held = [], []
    for c in cases:
        h = int(hashlib.sha256(repr(c[:3] + c[5:6]).encode()).hexdigest(), 16) % 10
        (held if h < 3 else dev).append(c)
    return dev, held


def run(target=0.99):
    """Calibrate on development cases only; grade on held-out cases the calibration never saw.
    Lenders whose method was reproduced from the lender's own published code (e.g. TD) are LOCKED:
    calibration never replaces their rules; their evidence is only reported."""
    cases = load_cases()
    if not cases:
        return (f"No qualifying cases. Add rows to {CASES} with evidence_kind = payout_statement or lender_calculator "
                f"and a source reference.")
    by = defaultdict(list)
    for c in cases:
        by[c[0]].append(c)
    report, cal = [], {}
    for lender, cs in by.items():
        base = POLICIES.get(lender, Policy(lender))
        dev, held = _split(cs)
        if base.verified:
            h1, _, _ = score(base, cs)
            report.append(f"{lender:22} LOCKED (method from lender's own code): {h1}/{len(cs)} real cases within 1%")
            continue
        best = max(grid(lender), key=lambda p: score(p, dev)[:2]) if dev else base
        h1, h50, errs = score(best, held)
        rate = h1 / len(held) if held else 0.0
        verified = len(held) >= MIN_HOLDOUT and rate >= target
        cal[lender] = {**asdict(best), "verified": verified, "dev_cases": len(dev), "holdout_cases": len(held),
                       "holdout_hit_rate_1pct": round(rate, 4)}
        report.append(f"{lender:22} dev={len(dev):3} holdout={len(held):3}  holdout within 1%: {h1}/{len(held)} ({rate:.1%}), "
                      f"{h50} within $50 -> {'VERIFIED' if verified else f'NOT YET (need >={MIN_HOLDOUT} held-out cases at >=99%)'}")
        worst = sorted((abs(e), i) for i, e in enumerate(errs) if e is not None)[-3:]
        for e, i in reversed(worst):
            if e > 0.01 * held[i][5]:
                report.append(f"     miss ${e:,.0f} on {held[i][6]} - check discount / origination posted rate / table date")
    CAL.write_text(json.dumps(cal, indent=2))
    return "\n".join(report)


def policy_for(lender):
    """Locked lender-code policy if one exists; else calibrated policy; else best-known default (verified=False)."""
    base = POLICIES.get(lender)
    if base is not None and base.verified:
        return base                                   # never overridden by calibration
    if CAL.exists():
        d = json.loads(CAL.read_text()).get(lender)
        if d:
            d = {k: v for k, v in d.items() if k in Policy.__dataclass_fields__}
            return Policy(**d)
    return POLICIES.get(lender, Policy(lender))
