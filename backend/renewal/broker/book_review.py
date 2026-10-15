"""Broker book review: find the deals in a broker's book where breaking the mortgage now (or soon) saves money.

For every deal (one row of a broker's funded/approved book):
  1. Balance today: the stated outstanding balance, or the original loan amount projected along the payment schedule.
  2. Penalty: the ratewatch engine with the lender's policy (TD reproduced exactly from TD's own calculator; other
     lenders are labelled ESTIMATE). Inputs: the lender's posted rates today (recorded/live) and the original
     discount (stated, from the posted rate at closing in the deal file, or from the lender's recorded posted rate on
     the closing date). Without those, only the three-month-interest floor is shown and the deal is flagged.
  3. Best available rate: lowest validated 5-year (or chosen term) offer on the live-rates board, or the broker's
     own target rate. Never an invented rate.
  4. Economics on one basis (same as extras.py): interest saved over min(remaining term, new term) minus penalty and
     fees; break-even month; years taken off the amortization if the client keeps today's payment; and whether
     waiting for a cheaper break date beats breaking now (waiting costs the higher interest meanwhile).
  5. Recommendation and ranking.
Variable-rate deals: the usual charge is three months' interest; shown as an estimate with that label.
Nothing is stored: deals are processed in memory and returned.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import replace
from datetime import date, timedelta

from ..ratewatch import history
from ..ratewatch.extras import _interest_path, monthly_payment
from ..ratewatch.ird import POLICIES, Mortgage, Policy, add_months, balance_after, maturity_of, months_between, penalty
from ..ratewatch.paths import DATA
from .book_ingest import Deal, deal_from_dict

# lender text in broker files -> (policy key, rate source id)
LENDER_ALIASES = [
    (("td", "toronto-dominion", "toronto dominion", "td canada trust", "td bank"), "TD", "P023"),
    (("rbc", "royal bank"), "RBC", "P021"),
    (("scotia", "bank of nova scotia", "bns"), "Scotiabank", "P025"),
    (("bmo", "bank of montreal"), "BMO", "P027"),
    (("cibc", "canadian imperial"), "CIBC", "P029"),
    (("national bank", "nbc", "banque nationale", "bnc"), "National Bank", "P031"),
    (("simplii",), "Simplii", "P034"),
    (("tangerine",), "Tangerine", "P033"),
    (("desjardins",), "Desjardins", "P035"),
    (("atb",), "ATB", "P039"),
    (("laurentian", "b2b"), "Laurentian", "P036"),
    (("manulife",), "Manulife Bank", "P038"),
    (("first national",), "First National", None),
    (("mcap",), "MCAP", None),
    (("rmg",), "RMG", None),
    (("cmls",), "CMLS", None),
    (("merix",), "Merix", None),
    (("lendwise",), "Lendwise", None),
    (("marathon",), "Marathon", None),
    (("equitable", "eq bank"), "Equitable Bank", None),
    (("home trust",), "Home Trust", None),
    (("haventree",), "Haventree", None),
    (("bridgewater",), "Bridgewater", None),
]
STRONG = 2000.0          # net benefit ($) above which an opportunity is "strong"
RENEWAL_WINDOW_DAYS = 120


def resolve_lender(name: str | None) -> tuple[Policy, str | None, str]:
    n = (name or "").lower()
    for keys, policy_key, sid in LENDER_ALIASES:
        if any(k in n for k in keys):
            return POLICIES[policy_key], sid, policy_key
    if "credit union" in n or " cu" in f" {n}" or "caisse" in n:
        return POLICIES["Credit union (generic)"], None, "Credit union (generic)"
    return Policy(name or "Unknown lender"), None, name or "Unknown lender"


def _board() -> dict:
    try:
        return json.loads((DATA / "live_board.json").read_text())
    except (OSError, ValueError):
        return {}


def best_offers(term_months: int = 60, board: dict | None = None, labelled_only: bool = True) -> list[dict]:
    """Validated lender-specific offers for a term from the live-rates board, lowest first.
    Only the lender's discounted/special rate counts (a posted rate is not what clients get). With labelled_only,
    a lender qualifies only if its page shows BOTH a posted and a special rate for the term, so the special rate is
    unambiguous; single unlabeled numbers (which may be variable or promotional) are listed but never the default."""
    board = board if board is not None else _board()
    out = []
    for group in ("banks", "credit_unions"):
        for r in board.get(group, []):
            if not r.get("lender_specific"):
                continue
            t = (r.get("rates") or {}).get(str(term_months)) or {}
            labelled = t.get("posted") is not None and t.get("special") is not None
            if labelled:
                rate = t["special"]
            elif not labelled_only and group == "credit_unions" and t:
                rate = min(v for v in t.values() if v is not None)
            else:
                continue
            out.append({"lender": r["name"], "rate": rate, "term_months": term_months, "labelled": labelled,
                        "posted": t.get("posted"), "as_of": r.get("as_of"), "source": r.get("tier_label")})
    return sorted(out, key=lambda o: o["rate"])


def _months_to_repay(balance: float, annual_rate: float, payment: float) -> float | None:
    j = (1 + annual_rate / 200) ** (1 / 6) - 1
    if payment <= balance * j:
        return None
    return -math.log(1 - balance * j / payment) / math.log(1 + j)


def _current_balance(d: Deal, as_of: date) -> tuple[float, str]:
    if d.balance_basis == "original" and d.closing_date and d.amort_months:
        m0 = Mortgage(d.balance, d.contract_rate, d.term_months or 60, d.closing_date, amort_months=d.amort_months)
        k = max(int(months_between(d.closing_date, as_of)), 0)
        return round(balance_after(m0, k), 2), f"projected from the original {d.balance:,.0f} over {k} months of payments"
    return d.balance, "as stated"


def review_deal(d: Deal, as_of: date, target_rate: float | None = None, new_term_months: int = 60, fees: float = 0.0,
                offers: list[dict] | None = None) -> dict:
    out = {"deal_id": d.deal_id, "borrower": d.borrower, "lender": d.lender, "closing_date": d.closing_date and d.closing_date.isoformat(),
           "maturity_date": d.maturity_date and d.maturity_date.isoformat(), "contract_rate": d.contract_rate,
           "rate_type": d.rate_type or "fixed", "issues": list(d.issues), "recommendation": "Review manually",
           "net_benefit": None, "status": "insufficient_data"}
    if d.balance is None or d.contract_rate is None or d.maturity_date is None or d.closing_date is None:
        out["issues"].append("cannot analyse without balance, rate, closing and maturity dates")
        return out
    if d.maturity_date <= as_of:
        out.update(status="matured", recommendation="Term has matured: renew or switch with no penalty")
        return out
    if d.closing_date > as_of:
        out.update(status="not_started", recommendation="Not funded yet on the review date")
        return out
    balance, basis = _current_balance(d, as_of)
    amort = d.amort_months or 300
    if d.amort_months is None:
        out["issues"].append("amortization not stated: 25 years assumed for projections")
    remaining_amort = max(amort - int(months_between(d.closing_date, as_of)), 12) if d.balance_basis == "original" else amort
    policy, sid, policy_name = resolve_lender(d.lender)
    days_left = (d.maturity_date - as_of).days
    out.update(balance_today=balance, balance_basis=basis, policy=policy_name,
               method_status="exact-method" if policy.verified else "estimate", days_to_maturity=days_left)

    # best new rate
    offers = offers if offers is not None else best_offers(new_term_months)
    if target_rate:
        best = {"lender": "broker target", "rate": target_rate, "term_months": new_term_months, "source": "entered by broker"}
    elif offers:
        best = offers[0]
    else:
        out["issues"].append("no validated market offers available (refresh the Live rates board or enter a target rate)")
        return out
    out["best_offer"] = best
    if best["rate"] >= d.contract_rate:
        out.update(status="no_opportunity", net_benefit=0.0,
                   recommendation=f"Current rate {d.contract_rate}% is not above the best offer {best['rate']}%")
        return out

    # penalty
    m = Mortgage(balance, d.contract_rate, d.term_months or months_between(d.closing_date, d.maturity_date), d.closing_date,
                 {}, d.discount, amort_months=remaining_amort, maturity=d.maturity_date)
    if (d.rate_type or "fixed") == "variable":
        three = round(balance * d.contract_rate / 100 / 4, 2)
        pen = {"penalty": three, "three_month": three, "ird": None, "method": "3-month (variable)", "remaining_months":
               round(months_between(as_of, d.maturity_date), 2)}
        out["method_status"] = "estimate"
        table = None
    else:
        table, seen = history.table_on(sid, as_of, max_age_days=14) if sid else ({}, None)
        if m.discount is None and d.posted_rate is None and sid:
            orig, oday = history.table_on(sid, d.closing_date, max_age_days=45)
            term = d.term_months or 60
            if term in orig and orig[term] >= d.contract_rate:
                m.discount = round(orig[term] - d.contract_rate, 4)
                out["issues"].append(f"original discount {m.discount}% from {d.lender}'s recorded posted rate on {oday}")
        elif d.posted_rate is not None and m.discount is None:
            m.posted_at_origination = {m.term_months: d.posted_rate}
        needs = []
        if not table:
            needs.append(f"{d.lender}'s current {'posted ' if policy.comparison != 'offered' else ''}rates")
        if policy.comparison == "posted_minus_discount" and m.discount is None and not m.posted_at_origination:
            needs.append("the original discount (welcome letter or commitment)")
        if needs:
            three = round(balance * d.contract_rate / 100 / 4, 2)
            out.update(status="needs_data", three_month_floor=three,
                       recommendation=f"Penalty is at least ${three:,.0f}; need {' and '.join(needs)} for the full IRD")
            out["issues"].append("IRD not computed: " + ", ".join(needs))
            return out
        try:
            pen = penalty(m, policy, table, as_of, current_offered=None)
        except ValueError as e:
            out.update(status="needs_data", recommendation=str(e))
            return out
        out["rates_as_of"] = seen
    out["penalty"] = {k: pen[k] for k in ("penalty", "three_month", "ird", "method", "remaining_months") if k in pen}

    # economics, one basis: interest saved over min(remaining term, new term) - penalty - fees
    horizon = max(min(int(pen["remaining_months"]), new_term_months), 1)
    old_i = _interest_path(balance, d.contract_rate, remaining_amort, horizon)
    new_i = _interest_path(balance, best["rate"], remaining_amort, horizon)
    saved = sum(old_i) - sum(new_i)
    net_now = saved - pen["penalty"] - fees
    cum, be = 0.0, None
    for k, (a, b) in enumerate(zip(old_i, new_i), start=1):
        cum += a - b
        if be is None and cum >= pen["penalty"] + fees:
            be = k
    pay = d.payment or monthly_payment(balance, d.contract_rate, remaining_amort)
    n_old = _months_to_repay(balance, d.contract_rate, pay)
    n_new = _months_to_repay(balance + pen["penalty"] + fees, best["rate"], pay)   # penalty added to the new loan
    years_saved = round((n_old - n_new) / 12, 2) if n_old and n_new else None

    # breaking later: cheaper penalty vs higher interest while waiting (next 6 months, monthly steps)
    wait = None
    if table is not None:
        for k in range(1, 7):
            day = add_months(as_of, k)
            if day >= d.maturity_date:
                break
            mk = replace(m, balance=balance_after(replace(m, balance=balance), k))
            pk = penalty(mk, policy, table, day)["penalty"]
            hk = max(min(int(months_between(day, d.maturity_date)), new_term_months), 1)
            saved_k = sum(_interest_path(mk.balance, d.contract_rate, remaining_amort - k, hk)) - \
                sum(_interest_path(mk.balance, best["rate"], remaining_amort - k, hk))
            waiting_cost = sum(old_i[:k]) - sum(new_i[:k])              # extra interest paid by not switching now
            net_k = saved_k - pk - fees - waiting_cost
            if wait is None or net_k > wait["net_benefit"]:
                wait = {"date": day.isoformat(), "penalty": round(pk, 2), "net_benefit": round(net_k, 2)}

    out.update(net_benefit=round(net_now, 2), interest_saved=round(saved, 2), horizon_months=horizon,
               break_even_months=be, years_saved_same_payment=years_saved, fees=fees)
    if wait and wait["net_benefit"] > net_now + 250:
        out["better_date"] = wait
    if days_left <= RENEWAL_WINDOW_DAYS:
        out.update(status="renewal_window",
                   recommendation=f"Maturity in {days_left} days: compare a switch at renewal (no penalty) with breaking now")
    elif net_now >= STRONG:
        out.update(status="strong", recommendation=f"Break now: about ${net_now:,.0f} net saving over {horizon} months")
    elif net_now > 0:
        out.update(status="possible", recommendation=f"Small saving (${net_now:,.0f}); confirm the payout statement first")
    else:
        out.update(status="no_opportunity", recommendation="Penalty outweighs the saving at today's rates")
    if out.get("better_date") and out["status"] != "renewal_window":
        w = out["better_date"]
        out["recommendation"] += f"; waiting until {w['date']} improves it to about ${w['net_benefit']:,.0f}"
        if out["status"] == "no_opportunity" and w["net_benefit"] > 0:
            out["status"] = "possible"
    if out["method_status"] == "estimate":
        out["issues"].append("penalty method for this lender is an estimate: get the payout statement")
    return out


def review_book(deals: list[dict | Deal], as_of: date | None = None, closed_from: date | None = None,
                closed_to: date | None = None, lender: str | None = None, target_rate: float | None = None,
                new_term_months: int = 60, fees: float = 0.0) -> dict:
    as_of = as_of or date.today()
    ds = [d if isinstance(d, Deal) else deal_from_dict(d) for d in deals]
    if closed_from:
        ds = [d for d in ds if d.closing_date and d.closing_date >= closed_from]
    if closed_to:
        ds = [d for d in ds if d.closing_date and d.closing_date <= closed_to]
    if lender:
        ds = [d for d in ds if lender.lower() in (d.lender or "").lower()]
    offers = best_offers(new_term_months)
    rows = [review_deal(d, as_of, target_rate, new_term_months, fees, offers) for d in ds]
    order = {"strong": 0, "possible": 1, "renewal_window": 2, "needs_data": 3, "no_opportunity": 4,
             "insufficient_data": 5, "matured": 6, "not_started": 7}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -(r.get("net_benefit") or 0)))
    totals = {s: sum(1 for r in rows if r["status"] == s) for s in order}
    return {"as_of": as_of.isoformat(), "deals_reviewed": len(rows), "summary": totals,
            "total_net_benefit": round(sum(r["net_benefit"] or 0 for r in rows if r["status"] in ("strong", "possible")), 2),
            "best_offer": offers[0] if offers and not target_rate else ({"lender": "broker target", "rate": target_rate} if target_rate else None),
            "top_offers": offers[:5],
            "unlabelled_offers": [o for o in best_offers(new_term_months, labelled_only=False) if not o["labelled"]][:10],
            "results": rows}


def to_csv(review: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["status", "deal_id", "borrower", "lender", "closing_date", "maturity_date", "contract_rate", "balance_today",
                "penalty", "penalty_method", "method_status", "best_rate", "best_rate_lender", "net_benefit", "break_even_months",
                "years_saved_same_payment", "better_date", "recommendation", "issues"])
    for r in review["results"]:
        p, b = r.get("penalty") or {}, r.get("best_offer") or {}
        w.writerow([r["status"], r["deal_id"], r.get("borrower"), r.get("lender"), r.get("closing_date"), r.get("maturity_date"),
                    r.get("contract_rate"), r.get("balance_today"), p.get("penalty"), p.get("method"), r.get("method_status"),
                    b.get("rate"), b.get("lender"), r.get("net_benefit"), r.get("break_even_months"),
                    r.get("years_saved_same_payment"), (r.get("better_date") or {}).get("date"), r.get("recommendation"),
                    "; ".join(r.get("issues", []))])
    return buf.getvalue()
