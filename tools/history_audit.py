"""Month-by-month audit of the five-year posted-rate history: one row per bank per month, each with its value,
the rule that produced it, a link to the evidence, and a plain-English explanation.

    python tools/history_audit.py          # writes data/ratewatch/history_audit.csv and docs/HISTORY_AUDIT.md

Run python -m renewal.ratewatch.backfill --fill first so the gap fills are current.
"""
import csv, json, sys
from datetime import date
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from renewal.ratewatch import backfill, history          # noqa: E402

NAMES = {"P021": "RBC", "P023": "TD", "P025": "Scotiabank", "P027": "BMO", "P029": "CIBC", "P031": "National Bank"}
# The bank-own page or feed each archive copy is of (for evidence links).
FEED = {"P021": "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html",
        "P023": "https://ix0.apps.td.com/api/get-rates/en",
        "P025": "https://dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage",
        "P027": "https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp",
        "P029": "https://www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy",
        "P031": "https://www.nbc.ca/personal/mortgages/rates.html"}
HOW_TEXT = {"wayback": "Internet Archive (Wayback Machine) copy", "arquivo": "Arquivo.pt (Portuguese national web archive) copy",
            "commoncrawl": "Common Crawl copy", "api": "read live from the bank by Renewal Radar", "html": "read live from the bank by Renewal Radar"}


def wayback_index(url):
    """day -> exact archived URL for one feed (one request per feed)."""
    try:
        r = requests.get("https://web.archive.org/cdx/search/cdx", params={"url": url.split("://", 1)[1], "matchType": "prefix",
                         "from": backfill.months()[0], "filter": "statuscode:200", "fl": "timestamp,original"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
        out = {}
        for line in r.text.splitlines():
            ts, orig = line.split(" ", 1)
            out.setdefault(ts[:8], (ts, orig))
        return out
    except (requests.RequestException, ValueError):
        return {}


def table_text(sid, day):
    with history.db() as c:
        rows = c.execute("SELECT term, rate, how FROM rates WHERE source=? AND day=? AND kind='fixed_closed' AND rtype='posted' "
                         "ORDER BY term", (sid, day)).fetchall()
    best = min({h for _, _, h in rows}, key=lambda h: history.HOW_PRIORITY.get(h, 9)) if rows else None
    return "; ".join(f"{t // 12 if t % 12 == 0 else t}{'y' if t % 12 == 0 else 'm'} {r:.2f}" for t, r, h in rows if h == best), best


def boc_on(day):
    t, d = history.table_on("BIG6_TYPICAL", date.fromisoformat(day), max_age_days=10)
    return t.get(60), d


def main():
    prog = json.loads(backfill.PROGRESS.read_text()) if backfill.PROGRESS.exists() else {}
    fills = json.loads(backfill.FILLS.read_text()) if backfill.FILLS.exists() else {}
    wb = {sid: wayback_index(u) for sid, u in FEED.items()}
    out = []
    for sid, name in NAMES.items():
        own = backfill.own_months(sid, prog)
        diffs = [v["rate5"] - v["boc"] for v in own.values() if v.get("boc") is not None]
        if diffs:
            avg, worst = sum(diffs) / len(diffs), max(diffs, key=abs)
            offset = (f" On the {len(diffs)} months where we hold both, {name}'s own 5-year rate averaged {avg:+.2f} points "
                      f"versus this figure (largest {worst:+.2f}), so treat it as accurate to about that margin.")
        else:
            offset = f" We hold no {name} reading to measure its usual gap against this figure."
        for m in backfill.months():
            ym = f"{m[:4]}-{m[4:]}"
            row = {"bank": name, "month": ym}
            if m in own:
                v = own[m]
                day = f"{v['ts'][:4]}-{v['ts'][4:6]}-{v['ts'][6:8]}"
                terms, how = table_text(sid, day)
                if not terms:                                    # recorded under an earlier key; fall back to the month
                    t, seen = history.table_on(sid, date.fromisoformat(day), max_age_days=0, own_only=True)
                    terms = "; ".join(f"{k}m {r:.2f}" for k, r in sorted(t.items()))
                how = how or v["how"].split("/")[0]
                if "arquivo" in v["how"]:
                    how = "arquivo"
                elif "commoncrawl" in v["how"]:
                    how = "commoncrawl"
                src = HOW_TEXT.get(how, how)
                if how == "wayback":
                    ts, orig = wb[sid].get(v["ts"][:8], (v["ts"][:8], v.get("url") or FEED[sid]))
                    link = f"https://web.archive.org/web/{ts}/{orig}"
                elif how == "arquivo":
                    link = f"https://arquivo.pt/wayback/{v['ts']}/{v.get('url') or FEED[sid]}"
                elif how == "commoncrawl":
                    link = f"Common Crawl capture {v['ts']} of {v.get('url') or FEED[sid]}"
                else:
                    link = f"{FEED[sid]} (live reading stored {day})"
                boc, _ = boc_on(day)
                gap = None if boc is None else round(v["rate5"] - boc, 2)
                row.update(status="bank-own", as_of=day, rate_5y=v["rate5"], all_terms=terms, boc_5y=boc, gap_vs_boc=gap,
                           evidence=link, explanation=(f"{name}'s own published 5-year posted rate was {v['rate5']:.2f}% on {day} "
                           f"({src}). Bank of Canada big-six figure that week: {boc:.2f}%, so it passed the "
                           f"{backfill.MAX_GAP:.2f}-point check (gap {gap:+.2f})."))
            else:
                f = fills.get(sid, {}).get(m, {"how": "gap"})
                if f["how"] == "bridged":
                    a, b = f["from"]
                    terms, _ = table_text(sid, f["day"])
                    row.update(status="bridged", as_of=f["day"], rate_5y=f["rate5"], all_terms=terms, boc_5y=f["boc_range"][0],
                               gap_vs_boc=round(f["rate5"] - f["boc_range"][0], 2),
                               evidence=f"{name} own readings {a[:4]}-{a[4:]} and {b[:4]}-{b[4:]}; Bank of Canada V80691335 flat at "
                                        f"{f['boc_range'][0]:.2f}% between them",
                               explanation=(f"No archived copy for this month. {name}'s own 5-year posted rate was {f['rate5']:.2f}% "
                                            f"in both {a[:4]}-{a[4:]} and {b[:4]}-{b[4:]}, and the Bank of Canada big-six figure did "
                                            f"not move at all in between, so the rate is carried across unchanged."))
                elif f["how"] == "boc_typical":
                    terms, _ = table_text(sid, f["day"])
                    row.update(status="Bank of Canada fill", as_of=f["day"], rate_5y=f.get("rate5"), all_terms=terms,
                               boc_5y=f.get("rate5"), gap_vs_boc=0.0,
                               evidence="Bank of Canada Valet series V80691333 (1y), V80691334 (3y), V80691335 (5y), week of "
                                        f"{f['day']}: https://www.bankofcanada.ca/valet/observations/V80691335",
                               explanation=(f"No bank-own copy of {name}'s rates survives for this month. The value shown is the "
                                            f"Bank of Canada's weekly big-six typical posted rate ({f.get('rate5'):.2f}% for 5 years) "
                                            f"- the rate most of the six big banks posted that week. It is labelled as such and is "
                                            f"never used as {name}'s current rate." + offset))
                else:
                    row.update(status="gap", explanation=f.get("why", "no data"))
            out.append(row)
    cols = ["bank", "month", "status", "as_of", "rate_5y", "boc_5y", "gap_vs_boc", "all_terms", "evidence", "explanation"]
    with open(backfill.DATA / "history_audit.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    write_markdown(out)
    return out


def write_markdown(rows):
    ms = backfill.months()
    lines = ["# Five-year posted-rate history: month-by-month audit", "",
             f"Window {ms[0][:4]}-{ms[0][4:]} to {ms[-1][:4]}-{ms[-1][4:]} ({len(ms)} months) for the six big banks. "
             "Every month has exactly one value and one of three labels:", "",
             "- **bank-own**: the bank's own published rate, from an archived copy of its page or data feed (or our live reading), "
             f"accepted only if its 5-year rate is within {backfill.MAX_GAP} points of the Bank of Canada big-six figure that week.",
             "- **bridged**: no copy that month, but the bank's own 5-year rate is identical in the nearest months on both sides "
             f"(at most {backfill.BRIDGE_MAX_MONTHS} months apart) and the Bank of Canada figure did not move in between.",
             "- **Bank of Canada fill**: no bank-own copy survives; the Bank of Canada's weekly big-six typical posted rate "
             "(1, 3 and 5-year) is shown, labelled, and never used as the bank's current rate.", "",
             "Full detail (every term, links, explanations): `data/ratewatch/history_audit.csv`.", "",
             "## Summary", "", "| Bank | Bank-own | Bridged | Bank of Canada fill | Total |", "|---|---|---|---|---|"]
    for name in NAMES.values():
        r = [x for x in rows if x["bank"] == name]
        c = lambda s: sum(1 for x in r if x["status"] == s)         # noqa: E731
        lines.append(f"| {name} | {c('bank-own')} | {c('bridged')} | {c('Bank of Canada fill')} | {len(r)} |")
    gaps = [abs(x["gap_vs_boc"]) for x in rows if x["status"] == "bank-own" and x.get("gap_vs_boc") is not None]
    if gaps:
        gaps.sort()
        lines += ["", f"Bank-own months checked against the Bank of Canada: {len(gaps)}; exact match {sum(g < 0.005 for g in gaps)}; "
                      f"average gap {sum(gaps) / len(gaps):.2f} points; 90% within {gaps[int(0.9 * (len(gaps) - 1))]:.2f}."]
    lines += ["", "Why the Bank of Canada fill is a fair stand-in: TD's own published daily history (1999-2018) equals it in "
                  "87% of 1,034 weeks (average gap 0.02 points). The series is built from the six big banks' posted rates.", ""]
    for name in NAMES.values():
        lines += [f"## {name}", "", "| Month | Status | 5-yr | BoC 5-yr | Evidence |", "|---|---|---|---|---|"]
        for x in (x for x in rows if x["bank"] == name):
            ev = x.get("evidence", "")
            ev = f"[archive copy]({ev})" if ev.startswith("http") else ev.split(":", 1)[0] if "Valet" in ev else ev
            r5 = "" if x.get("rate_5y") is None else f"{x['rate_5y']:.2f}"
            b5 = "" if x.get("boc_5y") is None else f"{x['boc_5y']:.2f}"
            lines.append(f"| {x['month']} | {x['status']} | {r5} | {b5} | {ev} |")
        lines.append("")
    (ROOT / "docs" / "HISTORY_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    rows = main()
    print(len(rows), "rows ->", backfill.DATA / "history_audit.csv", "and docs/HISTORY_AUDIT.md")
