"""Record First National's own prepayment-calculator answers as a fixture.

First National's calculator (firstnational.ca/residential/mortgage-calculators/prepayment-calculator)
computes server-side through its RemainingBalanceFixed service, so unlike the lenders whose
calculator ships as JavaScript there is no code to replay locally: its answers are recorded,
RBC-style, and backtest.first_national_cases scores our engine against the recording.

    python tools/record_first_national.py [n]

Cases are generated deterministically (seed 2039), posted one at a time with a polite pause,
and appended to a JSONL checkpoint as they land, so the run can be stopped and resumed; only
missing cases are requested on a re-run. Before recording, a stub-sensitive probe case is used
to pin the calculator's effective "today" (its servers and this machine may disagree by a day),
and recording aborts if the probe matches no candidate date.
"""
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import requests  # noqa: E402

from renewal.ratewatch.ird import TERMS, Mortgage, POLICIES, add_months, monthly_payment, penalty  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "first_national_calculator_2026-10-28.json"
CHECKPOINT = ROOT / "data" / "ratewatch" / "first_national_oracle" / "recorded.jsonl"
FORM = "https://www.firstnational.ca/calcapi/prepaycalculator/remainingfixed?culture=en-CA"
ACTION = ("https://www.firstnational.ca/residential/mortgage-calculators/"
          "prepayment-calculator/RemainingBalanceFixed")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"}
N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
SEED = 2039


def generate(payout: date):
    rng = random.Random(SEED)
    cases = []
    for _ in range(N):
        balance = round(rng.uniform(50_000, 1_500_000), 2)
        contract = round(rng.uniform(1.5, 8.5), 2)
        posted = round(rng.uniform(1.0, 8.5), 2)
        term = rng.choice([12, 24, 36, 48, 60, 60, 60, 84, 120])
        rem_whole = rng.randint(1, min(term - 1, 119))
        stub = rng.randint(0, 29)
        maturity = add_months(payout, rem_whole) + timedelta(days=stub)
        payment = round(monthly_payment(balance, contract, 300), 2)
        cases.append({"balance": balance, "contract": contract, "posted": posted,
                      "term_months": term, "payout": payout.isoformat(),
                      "maturity": maturity.isoformat(), "payment": payment})
    return cases


def payload(c: dict, payout: date) -> dict:
    mat = date.fromisoformat(c["maturity"])
    return {"type-mortgage": "2", "CurrentInterestRateText": f"{c['contract']:.2f}",
            "OutstandingBalanceText": f"{c['balance']:.2f}",
            "NextPaymentDateText": (payout + timedelta(days=15)).strftime("%d/%m/%Y"),
            "OriginalNumberOfMonths": str(c["term_months"]),
            "MaturityDateText": mat.strftime("%d/%m/%Y"),
            "PaymentFrequency": "12", "PaymentAmountText": f"{c['payment']:.2f}",
            "PostedInterestRateText": f"{c['posted']:.2f}",
            "ReceivedCashBack": "0", "CashBackText": ""}


class Calculator:
    def __init__(self):
        self.s = requests.Session()

    def ask(self, c: dict, payout: date):
        for attempt in range(5):
            try:
                r = self.s.post(ACTION, data=payload(c, payout), headers=H, timeout=45)
                obj = json.loads(r.text)["Object"]
                return float(obj["Payment"].replace("$", "").replace(",", ""))
            except Exception:
                if attempt == 1:
                    try:
                        self.s.get(FORM, headers=H, timeout=45)   # refresh the session
                    except Exception:
                        pass
                time.sleep(5 * (attempt + 1))
        return None


def expected(c: dict, payout: date) -> float:
    mat = date.fromisoformat(c["maturity"])
    m = Mortgage(c["balance"], c["contract"], c["term_months"], add_months(mat, -c["term_months"]),
                 discount=0.0, maturity=mat, payment=c["payment"])
    return penalty(m, POLICIES["First National"], {t: c["posted"] for t in TERMS}, payout)["penalty"]


def main():
    calc = Calculator()
    try:
        calc.s.get(FORM, headers=H, timeout=45)
    except Exception:
        pass
    vm_today = date.today()
    probe = {"balance": 400000.0, "contract": 6.00, "posted": 4.00, "term_months": 60,
             "maturity": (add_months(vm_today, 15) + timedelta(days=15)).isoformat(),
             "payment": 2559.23}
    answer = calc.ask(probe, vm_today)
    if answer is None:
        raise SystemExit("probe failed: the calculator did not answer")
    server_today = None
    for cand in (vm_today, vm_today - timedelta(days=1), vm_today + timedelta(days=1)):
        if abs(expected(probe, cand) - answer) < 0.005:
            server_today = cand
            break
    if server_today is None:
        raise SystemExit(f"probe answer {answer} matches no candidate date; not recording")
    print(f"calculator's effective today: {server_today} (this machine: {vm_today})", flush=True)

    cases = generate(server_today)
    done = {}
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text().splitlines():
            rec = json.loads(line)
            done[rec["idx"]] = rec
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT, "a") as f:
        for idx, c in enumerate(cases):
            if idx in done:
                continue
            charge = calc.ask(c, server_today)
            if charge is None:
                print(f"case {idx}: no answer after retries (left for a re-run)", flush=True)
                continue
            rec = {"idx": idx, **c, "fn_charge": charge}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[idx] = rec
            if len(done) % 100 == 0:
                print(f"{len(done)}/{N} recorded", flush=True)
            time.sleep(1.6)
    if len(done) < N:
        print(f"recorded {len(done)}/{N}; re-run to top up the missing cases")
        return
    blob = {"lender": "First National", "source": "First National's online prepayment calculator "
            "(firstnational.ca, RemainingBalanceFixed service), answers recorded by "
            "tools/record_first_national.py", "recorded": server_today.isoformat(),
            "cases": [{k: done[i][k] for k in ("balance", "contract", "posted", "term_months",
                                               "payout", "maturity", "payment", "fn_charge")}
                      for i in range(N)]}
    FIXTURE.write_text(json.dumps(blob, indent=1))
    print(f"wrote {FIXTURE} with {N} cases")


if __name__ == "__main__":
    main()
