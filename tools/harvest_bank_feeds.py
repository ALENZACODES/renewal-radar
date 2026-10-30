"""Gentle, resumable Wayback harvest of bank-own rate feeds, one capture per month (newest first within a month).
Same parsers and Bank of Canada validation as the backfill; accepted months are saved as how='wayback'.
Coverage then counts them automatically (backfill.own_months reads validated bank-own rows from the database).

    python tools/harvest_bank_feeds.py            # BMO include, CIBC feed, TD calculator feed
"""
import json, sys, time
from datetime import date, datetime
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from renewal.ratewatch import backfill, history          # noqa: E402

PACE = 12
H = {"User-Agent": "Mozilla/5.0 (research; Renewal Radar history backfill)"}
DONE = backfill.DATA / "harvest_done.json"
FEEDS = [
    ("P027", "bmo_include", "www.bmo.com/bmocda/templates/json_mortgage_include.jsp", None),
    ("P029", "cibc_js", "www.cibconline.cibc.com/ebm-pno/api/v1/json/productRatesLegacy", None),
    ("P023", "td_json", "ix0.apps.td.com/api/get-rates/en", None),
    ("P025", "scotia_json", "dmtsms.scotiabank.com/api/rates/daily/nonspecialmortgage", None),
    ("P021", "html", "www.rbcroyalbank.com/mortgages/mortgage-rates.html", None),
    ("P031", "html", "www.nbc.ca/personal/mortgages/rates.html", None),
]
PER_MONTH = 5


def get(url, **kw):
    for attempt in range(6):
        try:
            r = requests.get(url, headers=H, timeout=120, **kw)
            if r.status_code not in (429, 503):
                return r
            print(f"{datetime.now():%H:%M} busy {r.status_code}; waiting {2 * (attempt + 1)} min", flush=True)
            time.sleep(120 * (attempt + 1))
        except requests.RequestException as e:
            print(f"{datetime.now():%H:%M} {type(e).__name__}; retry", flush=True)
            time.sleep(60)
    return None


def main():
    done = json.loads(DONE.read_text()) if DONE.exists() else {}
    window = set(backfill.months())
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--banks=")), None)
    for sid, kind, url, must in FEEDS:
        if only and sid not in only:
            continue
        have = set(backfill.own_months(sid, {}))
        r = get("https://web.archive.org/cdx/search/cdx", params={"url": url, "matchType": "prefix", "from": min(window),
                "filter": "statuscode:200", "fl": "timestamp,original"})
        time.sleep(PACE)
        if r is None:
            print(sid, "capture list unavailable; rerun later", flush=True)
            continue
        by_month = {}
        for line in r.text.splitlines():
            ts, orig = line.split(" ", 1)
            if ts[:6] in window and (must is None or must in orig.upper()):
                by_month.setdefault(ts[:6], []).append((ts, orig))
        print(sid, len(by_month), "months with captures;", len(have & set(by_month)), "already bank-own", flush=True)
        for m in sorted(by_month):
            if m in have or done.get(f"{sid}:{m}") == "ok":
                continue
            for ts, orig in sorted(by_month[m], reverse=True)[:PER_MONTH]:
                if done.get(f"{sid}:{ts}") == "rejected":
                    continue
                resp = get(f"https://web.archive.org/web/{ts}id_/{orig}")
                time.sleep(PACE)
                if resp is None or not resp.ok:
                    continue
                rows = backfill.parse(kind, resp.text)
                day = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
                ok, rate5, boc = backfill.validate_month(rows, day)
                print(f"{sid} {ts[:8]} wb/{kind:11} rows={len(rows):3} 5y={rate5} boc={boc} {'OK' if ok else 'reject'}", flush=True)
                if ok:
                    history.save(sid, day.isoformat(), rows, "wayback")
                    done[f"{sid}:{m}"] = "ok"
                    break
                done[f"{sid}:{ts}"] = "rejected"
            DONE.write_text(json.dumps(done, indent=1))
    backfill.fill_gaps()
    rep = backfill.report()
    for sid, b in rep["banks"].items():
        print(sid, f"own {b['covered']} + bridged {b['bridged']} + BoC {b['boc_typical']} = {b['covered_with_fills']}/{rep['months']}")


if __name__ == "__main__":
    main()
