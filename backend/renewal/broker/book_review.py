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
from dataclasses import replace
from datetime import date

from ..ratewatch import history
from ..ratewatch.ird import POLICIES, Mortgage, Policy, add_months, balance_after, months_between, penalty
from ..ratewatch.paths import DATA
from .book_ingest import Deal, deal_from_dict
from .book_values import csv_cell
from .book_validation import (
    lender_alias_matches, offer_issues, safe_review_date, summarize_diagnostics,
    unique_deals, validate_deal, validate_rate_table,
)
from .book_economics import (
    interest_comparison, project_balance, same_payment_projection, wait_economics,
)

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
    (("cmls",), "CMLS", "ALT09"),
    (("merix",), "Merix", "ALT12"),
    (("lendwise",), "Lendwise", None),
    (("marathon",), "Marathon", None),
    (("equitable", "eq bank"), "Equitable Bank", "ALT02"),
    (("home trust",), "Home Trust", "ALT01"),
    (("haventree",), "Haventree", "ALT03"),
    (("bridgewater",), "Bridgewater", "ALT05"),
    # B / private lenders (registered on the Live rates board as ALT01-ALT30)
    (("home trust",), "ALT", "ALT01"),
    (("equitable bank",), "ALT", "ALT02"),
    (("haventree bank",), "ALT", "ALT03"),
    (("community trust",), "ALT", "ALT04"),
    (("bridgewater bank",), "ALT", "ALT05"),
    (("wealth one bank of canada",), "ALT", "ALT06"),
    (("rfa bank of canada",), "ALT", "ALT07"),
    (("peoples group",), "ALT", "ALT08"),
    (("cmls financial",), "ALT", "ALT09"),
    (("mcan financial",), "ALT", "ALT10"),
    (("optimum mortgage",), "ALT", "ALT11"),
    (("merix financial",), "ALT", "ALT12"),
    (("cameron stephens",), "ALT", "ALT13"),
    (("effort trust",), "ALT", "ALT14"),
    (("questbank",), "ALT", "ALT15"),
    (("keb hana bank canada",), "ALT", "ALT16"),
    (("homeequity bank",), "ALT", "ALT17"),
    (("b2b bank",), "ALT", "ALT18"),
    (("fisgard capital",), "ALT", "ALT19"),
    (("antrim investments",), "ALT", "ALT20"),
    (("cmi financial group",), "ALT", "ALT21"),
    (("brightpath capital",), "ALT", "ALT22"),
    (("hillmount capital",), "ALT", "ALT23"),
    (("atrium mortgage investment corp",), "ALT", "ALT24"),
    (("firm capital",), "ALT", "ALT25"),
    (("trez capital",), "ALT", "ALT26"),
    (("alpine credits",), "ALT", "ALT27"),
    (("fairstone",), "ALT", "ALT28"),
    (("neighbourhood holdings",), "ALT", "ALT29"),
    (("bloom finance",), "ALT", "ALT30"),
]
STRONG = 2000.0          # net benefit ($) above which an opportunity is "strong"
RENEWAL_WINDOW_DAYS = 120


def resolve_lender(name: str | None) -> tuple[Policy, str | None, str]:
    n = (name or "").lower()
    for keys, policy_key, sid in LENDER_ALIASES:
        if any(lender_alias_matches(n, k) for k in keys):
            if policy_key == "ALT":                   # B/private lender: compares against its own current rates
                return Policy(name or "B lender", comparison="offered"), sid, name or "B lender"
            return POLICIES[policy_key], sid, policy_key
    if "credit union" in n or " cu" in f" {n}" or "caisse" in n:
        return POLICIES["Credit union (generic)"], None, "Credit union (generic)"
    return Policy(name or "Unknown lender"), None, name or "Unknown lender"


def lender_rates(sids: set, as_of: date, fetch_live: bool = True) -> dict:
    """{sid: (posted_table, source_label)} for every lender in the book, read ONCE per review.

    For today's review each lender goes through the same chain as the Live rates page:
      1. a reading already recorded today/yesterday (no network)
      2. live.resolve: lender feed/page -> second lender source or rediscovered page -> last good reading
         (up to 14 days) -> newest web-archive copy, each validated before use
      3. the most recent recorded reading up to 14 days old
    For a past review date only readings recorded on or before that date are used (never later data).
    A lender with no valid reading returns ({}, reason); the deal is then flagged, never estimated."""
    from ..ratewatch import live
    out = {}
    by_sid = {l[0]: l for l in live.LENDERS}
    today = date.today()
    anchor = None
    for sid in sorted(s for s in sids if s):
        fresh, day = history.table_on(sid, as_of, max_age_days=1, own_only=True)
        if fresh:
            out[sid] = (fresh, f"recorded {day}")
            continue
        if as_of >= today and fetch_live and sid in by_sid:
            try:
                anchor = anchor or live.market_anchor()
                row = live.resolve(by_sid[sid], anchor)
                table = {int(t): v["posted"] for t, v in (row.get("rates") or {}).items() if v.get("posted") is not None}
                if table and row.get("lender_specific"):
                    out[sid] = (table, f"{row['tier_label']} ({row.get('as_of')})")
                    continue
            except Exception:                                  # network trouble: fall through to recorded data
                pass
        recent, day = history.table_on(sid, as_of, max_age_days=14, own_only=True)
        out[sid] = (recent, f"recorded {day}") if recent else ({}, "no valid reading in the last 14 days")
    return out


def _board() -> dict:
    try:
        return json.loads((DATA / "live_board.json").read_text())
    except (OSError, ValueError):
        return {}


def best_offers(term_months: int = 60, board: dict | None = None, labelled_only: bool = True,
                as_of: date | None = None) -> list[dict]:
    """Validated lender-specific offers for a term from the live-rates board, lowest first.
    Only the lender's discounted/special rate counts (a posted rate is not what clients get). With labelled_only,
    a lender qualifies only if its page shows BOTH a posted and a special rate for the term, so the special rate is
    unambiguous; single unlabeled numbers (which may be variable or promotional) are listed but never the default."""
    board = board if board is not None else _board()
    as_of = safe_review_date(as_of)
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
            offer = {"lender": r["name"], "rate": rate, "term_months": term_months, "labelled": labelled,
                     "posted": t.get("posted"), "as_of": r.get("as_of"), "source": r.get("tier_label")}
            checks = offer_issues(offer, as_of)
            if labelled and any(issue.blocking for issue in checks):
                continue
            if not labelled and not labelled_only:
                offer["warnings"] = ["Unlabelled: not used for recommendations."]
            else:
                offer["warnings"] = [issue.message for issue in checks]
            out.append(offer)
    return sorted(out, key=lambda o: o["rate"])


def _current_balance(d: Deal, as_of: date) -> tuple[float, str]:
    result = project_balance(d, as_of)
    return result["balance"], result["basis"]


def review_deal(d: Deal, as_of: date, target_rate: float | None = None, new_term_months: int = 60, fees: float = 0.0,
                offers: list[dict] | None = None, lender_tables: dict | None = None) -> dict:
    out = {"deal_id": d.deal_id, "borrower": d.borrower, "lender": d.lender, "closing_date": d.closing_date and d.closing_date.isoformat(),
           "maturity_date": d.maturity_date and d.maturity_date.isoformat(), "contract_rate": d.contract_rate,
           "rate_type": d.rate_type, "issues": list(d.issues), "recommendation": "Review manually",
           "net_benefit": None, "status": "insufficient_data"}
    validation = validate_deal(d, as_of)
    out["validation"] = [issue.as_dict() for issue in validation]
    if any(issue.blocking for issue in validation):
        out.update(status="needs_data", recommendation="Confirm the highlighted source fields before calculating.")
        out["issues"].extend(issue.message for issue in validation)
        return out
    if d.balance is None or d.contract_rate is None or d.maturity_date is None or d.closing_date is None:
        out["issues"].append("cannot analyse without balance, rate, closing and maturity dates")
        return out
    if d.maturity_date <= as_of:
        out.update(status="matured", recommendation="Term has matured: renew or switch with no penalty")
        return out
    if d.closing_date > as_of:
        out.update(status="not_started", recommendation="Not funded yet on the review date")
        return out
    try:
        projection = project_balance(d, as_of)
    except ValueError as exc:
        out.update(status="needs_data", recommendation=str(exc))
        return out
    balance, basis = projection["balance"], projection["basis"]
    if balance <= 0:
        out.update(status="matured", recommendation="The scheduled balance is repaid; obtain the discharge statement.")
        return out
    remaining_amort = projection["remaining_amort_months"]
    if d.balance_basis == "current" and d.amort_basis == "original":
        remaining_amort = max(d.amort_months - int(months_between(d.closing_date, as_of)), 1)
    out["issues"].extend(projection["assumptions"])
    out["balance_projection"] = projection
    policy, sid, policy_name = resolve_lender(d.lender)
    days_left = (d.maturity_date - as_of).days
    out.update(balance_today=balance, balance_basis=basis, policy=policy_name,
               method_status="exact-method" if policy.verified else "estimate", days_to_maturity=days_left)

    # best new rate
    offers = offers if offers is not None else best_offers(new_term_months, as_of=as_of)
    if target_rate:
        best = {"lender": "broker target", "rate": target_rate, "term_months": new_term_months,
                "source": "entered by broker", "labelled": True, "as_of": as_of.isoformat(), "warnings": []}
    elif offers:
        best = offers[0]
    else:
        out["issues"].append("no validated market offers available (refresh the Live rates board or enter a target rate)")
        out.update(status="needs_data", recommendation="Obtain a current labelled lender offer or enter a broker target.")
        return out
    out["best_offer"] = best
    out["issues"].extend(best.get("warnings", []))
    out["issues"].append("Offer eligibility and availability require the lender's written confirmation.")
    if best["rate"] >= d.contract_rate:
        out.update(status="no_opportunity", net_benefit=0.0,
                   recommendation=f"Current rate {d.contract_rate}% is not above the best offer {best['rate']}%")
        return out

    # penalty
    m = Mortgage(balance, d.contract_rate, d.term_months, d.closing_date,
                 {d.term_months: d.posted_rate} if d.posted_rate is not None else {},
                 d.discount, amort_months=remaining_amort, maturity=d.maturity_date)
    if d.rate_type == "variable":
        three = round(balance * d.contract_rate / 100 / 4, 2)
        pen = {"penalty": three, "three_month": three, "ird": None, "method": "3-month (variable)", "remaining_months":
               round(months_between(as_of, d.maturity_date), 2)}
        out["method_status"] = "estimate"
        table = None
    else:
        table, seen = (lender_tables or {}).get(sid) or (history.table_on(sid, as_of, max_age_days=14, own_only=True) if sid else ({}, None))
        if (m.discount is None or policy.three_month_basis == "posted_at_origination") and d.posted_rate is None and sid:
            orig, oday = history.table_on(sid, d.closing_date, max_age_days=45)
            term = d.term_months or 60
            if term in orig and orig[term] >= d.contract_rate:
                if m.discount is None:
                    m.discount = round(orig[term] - d.contract_rate, 4)
                m.posted_at_origination = {term: orig[term]}
                how = history.provenance(sid, d.closing_date, max_age_days=45)
                src = f"from {d.lender} on {oday}" if how not in history.FILL_HOWS else f"({history.FILL_LABEL[how]}, {oday})"
                out["issues"].append(f"original discount {m.discount}%; recorded posted rate {orig[term]}% {src}.")
                if how in history.FILL_HOWS:
                    out["method_status"] = "estimate"
                    out["issues"].append("Original posted rate is a labelled gap fill, not the lender's own record: "
                                         "confirm the discount from the commitment letter.")
        needs = []
        if not validate_rate_table(table):
            needs.append(f"{d.lender}'s current {'posted ' if policy.comparison != 'offered' else ''}rates")
        if policy.three_month_basis == "posted_at_origination" and not m.posted_at_origination:
            needs.append("the original posted rate used for the three-month charge")
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
        out["rates_source"] = seen
    out["penalty"] = {k: pen[k] for k in ("penalty", "three_month", "ird", "method", "remaining_months") if k in pen}

    # economics, one basis: interest saved over min(remaining term, new term) - penalty - fees
    horizon = max(min(int(pen["remaining_months"]), new_term_months), 1)
    economics = interest_comparison(balance, d.contract_rate, best["rate"], remaining_amort,
                                    horizon, pen["penalty"], fees)
    saved, net_now, be = economics["interest_saved"], economics["net_benefit"], economics["break_even_months"]
    try:
        payment_projection = same_payment_projection(
            balance, d.contract_rate, best["rate"], remaining_amort, pen["penalty"], fees,
            d.payment, d.frequency or "monthly",
        )
    except ValueError as exc:
        payment_projection = {"years_saved": None, "label": str(exc)}
    years_saved = payment_projection["years_saved"]
    out["economics"] = economics
    out["same_payment_projection"] = payment_projection

    # breaking later: cheaper penalty vs higher interest while waiting (next 6 months, monthly steps)
    wait = None
    if table is not None:
        for k in range(1, min(7, horizon)):
            day = add_months(as_of, k)
            if day >= d.maturity_date:
                break
            mk = replace(m, balance=balance_after(replace(m, balance=balance), k))
            if mk.balance <= 0:
                break
            try:
                pk = penalty(mk, policy, table, day)["penalty"]
            except ValueError:
                out["issues"].append(f"No complete comparison table for {day}; that waiting date was omitted.")
                continue
            comparison = wait_economics(balance, d.contract_rate, best["rate"], remaining_amort,
                                        horizon, k, pk, fees)
            if comparison is None:
                continue
            net_k = comparison["net_benefit"]
            if wait is None or net_k > wait["net_benefit"]:
                wait = {"date": day.isoformat(), "penalty": round(pk, 2), "net_benefit": round(net_k, 2),
                        "comparison": comparison}

    out.update(net_benefit=round(net_now, 2), interest_saved=round(saved, 2), horizon_months=horizon,
               break_even_months=be, years_saved_same_payment=years_saved, fees=fees)
    if wait and wait["net_benefit"] > net_now + 250:
        out["better_date"] = wait
    if days_left <= RENEWAL_WINDOW_DAYS:
        out.update(status="renewal_window",
                   recommendation=f"Maturity in {days_left} days: compare a switch at renewal (no penalty) with breaking now")
    elif net_now >= STRONG:
        out.update(status="strong", recommendation=f"Potential switch: about ${net_now:,.0f} net saving over {horizon} months; obtain written quotes")
    elif net_now > 0:
        out.update(status="possible", recommendation=f"Small saving (${net_now:,.0f}); confirm the payout statement first")
    else:
        out.update(status="no_opportunity", recommendation="Penalty outweighs the saving at today's rates")
    if out.get("better_date") and out["status"] != "renewal_window":
        w = out["better_date"]
        out["recommendation"] = f"Compare a switch on {w['date']}: projected net saving ${w['net_benefit']:,.0f} on the same end date"
        if out["status"] == "no_opportunity" and w["net_benefit"] > 0:
            out["status"] = "possible"
    if out["method_status"] == "estimate":
        out["issues"].append("penalty method for this lender is an estimate: get the payout statement")
    if out["status"] == "strong" and (
        out["method_status"] == "estimate" or projection["estimated"] or best.get("warnings")
    ):
        out["status"] = "possible"
        out["recommendation"] = "Estimated opportunity: confirm balance, rates, and written payout before acting."
    out["opportunity_net_benefit"] = max(0.0, net_now, wait["net_benefit"] if wait else 0.0)
    return out


def review_book(deals: list[dict | Deal], as_of: date | None = None, closed_from: date | None = None,
                closed_to: date | None = None, lender: str | None = None, target_rate: float | None = None,
                new_term_months: int = 60, fees: float = 0.0) -> dict:
    as_of = safe_review_date(as_of)
    if not 0 < len(deals) <= 2000:
        raise ValueError("review between 1 and 2000 deals at a time")
    ds = [d if isinstance(d, Deal) else deal_from_dict(
        {**d, "deal_id": d.get("deal_id") or f"row-{index + 1}"}
    ) for index, d in enumerate(deals)]
    if closed_from:
        ds = [d for d in ds if d.closing_date and d.closing_date >= closed_from]
    if closed_to:
        ds = [d for d in ds if d.closing_date and d.closing_date <= closed_to]
    if lender:
        ds = [d for d in ds if lender.lower() in (d.lender or "").lower()]
    ds, duplicates = unique_deals(ds)
    snapshot = _board()
    if as_of >= date.today():
        try:                                                   # keeps the offers board fresh (background refresh)
            from ..ratewatch import live
            snapshot = live.board() or snapshot
        except Exception:
            pass
    offers = best_offers(new_term_months, board=snapshot, as_of=as_of) if target_rate is None else []
    tables = lender_rates({resolve_lender(d.lender)[1] for d in ds}, as_of)
    rows = [review_deal(d, as_of, target_rate, new_term_months, fees, offers=offers, lender_tables=tables) for d in ds]
    order = {"strong": 0, "possible": 1, "renewal_window": 2, "needs_data": 3, "no_opportunity": 4,
             "insufficient_data": 5, "matured": 6, "not_started": 7}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -(r.get("opportunity_net_benefit") or 0)))
    totals = {s: sum(1 for r in rows if r["status"] == s) for s in order}
    return {"as_of": as_of.isoformat(), "deals_reviewed": len(rows), "summary": totals,
            "total_net_benefit": round(sum(r.get("opportunity_net_benefit") or 0 for r in rows if r["status"] in ("strong", "possible")), 2),
            "best_offer": offers[0] if offers and not target_rate else ({"lender": "broker target", "rate": target_rate} if target_rate else None),
            "top_offers": offers[:5],
            "unlabelled_offers": [o for o in best_offers(new_term_months, board=snapshot, labelled_only=False, as_of=as_of) if not o["labelled"]][:10],
            "duplicates": duplicates, "diagnostics": summarize_diagnostics(rows),
            "deals_input": len(deals),
            "results": rows}


def to_csv(review: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["status", "deal_id", "borrower", "lender", "closing_date", "maturity_date", "contract_rate", "balance_today",
                "penalty", "penalty_method", "method_status", "best_rate", "best_rate_lender", "net_benefit", "break_even_months",
                "years_saved_same_payment", "better_date", "recommendation", "issues"])
    for r in review["results"]:
        p, b = r.get("penalty") or {}, r.get("best_offer") or {}
        w.writerow([csv_cell(value) for value in [r["status"], r["deal_id"], r.get("borrower"), r.get("lender"), r.get("closing_date"), r.get("maturity_date"),
                    r.get("contract_rate"), r.get("balance_today"), p.get("penalty"), p.get("method"), r.get("method_status"),
                    b.get("rate"), b.get("lender"), r.get("net_benefit"), r.get("break_even_months"),
                    r.get("years_saved_same_payment"), (r.get("better_date") or {}).get("date"), r.get("recommendation"),
                    "; ".join(r.get("issues", []))]])
    return buf.getvalue()
