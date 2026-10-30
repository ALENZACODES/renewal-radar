"""Run every lender oracle in renewal.ratewatch.backtest and save one report.

    PYTHONPATH=backend python tools/run_oracle_battery.py [n]

Each oracle replays n random mortgages through the lender's own published
calculator code (fetched under data/ratewatch/<lender>_oracle/, never
committed) and compares the charge with this app's engine, cent by cent.
Lenders whose calculator code has not been fetched are reported as errors,
not skipped silently. The report lands in data/ratewatch/oracle_battery_report.json.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from renewal.ratewatch import backtest as bt  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000

ORACLES = [
    ("TD", lambda: bt.td_oracle(N)),
    ("Scotiabank", lambda: bt.scotia_oracle(N)),
    ("CIBC", lambda: bt.cibc_oracle(N)),
    ("BMO", lambda: bt.bmo_oracle(N)),
    ("National Bank", lambda: bt.nbc_oracle(N)),
    ("RBC (recorded fixture)", lambda: bt.rbc_cases()),
    ("First National (recorded fixture)", lambda: bt.first_national_cases()),
    ("MCAP (recorded fixture)", lambda: bt.mcap_cases()),
    ("RMG (recorded fixture)", lambda: bt.rmg_cases()),
    ("Community Trust", lambda: bt.community_trust_oracle(N)),
    ("Desjardins", lambda: bt.desjardins_oracle(N)),
    ("Tangerine", lambda: bt.tangerine_oracle(N)),
    ("Simplii", lambda: bt.simplii_oracle(N)),
    ("ATB", lambda: bt.atb_oracle(N)),
    ("Haventree", lambda: bt.haventree_oracle(N)),
    ("Laurentian", lambda: bt.laurentian_oracle(N)),
    ("Equitable Bank", lambda: bt.equitable_oracle(N)),
    ("Bridgewater", lambda: bt.bridgewater_oracle(N)),
]


def main():
    results = {}
    for name, fn in ORACLES:
        t0 = time.time()
        try:
            r = fn()
            r["seconds"] = round(time.time() - t0, 1)
            results[name] = r
            print(f"{name}: {r.get('exact_to_the_cent')}/{r.get('cases')} exact "
                  f"({r.get('exact_rate')}) in {r['seconds']}s", flush=True)
        except Exception as exc:  # keep going; record honestly
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"{name}: ERROR {exc}", flush=True)
    results["td_history_vs_boc"] = bt.td_history_vs_boc()
    results["scraped_vs_boc"] = {k: (str(v) if k == "per_bank_rows" else v)
                                 for k, v in bt.scraped_vs_boc().items()}
    out = bt.DATA / "oracle_battery_report.json"
    out.write_text(json.dumps({"run": date.today().isoformat(), "n_per_oracle": N,
                               "results": results}, indent=2, default=str))
    print("wrote", out)


if __name__ == "__main__":
    main()
