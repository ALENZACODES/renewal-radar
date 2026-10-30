"""Record MCAP's and RMG's own prepayment-calculator answers as fixtures.

Both lenders link a vendor-hosted prepayment calculator (one instance per lender) that computes
server-side, so there is no code to replay locally: answers are recorded, RBC-style, and
backtest.mcap_cases / backtest.rmg_cases score our engine against the recording, including the
"reinvestment rate" the calculator prints for each case (which pins the term-band rule).

    python tools/record_mcap.py [mcap|rmg|both]

Cases are deterministic, posted one at a time with a polite pause, and appended to a JSONL
checkpoint as they land, so the run can be stopped and resumed; only missing cases are
requested on a re-run. Balances stay under $1,000,000 (the calculator rejects seven figures).
"""
import json
import re
import sys
import time
import html as H
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import requests  # noqa: E402

from renewal.ratewatch.ird import monthly_payment  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.ppcalculators.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"}
INSTANCES = {
    "mcap": {"id": "876145", "lender": "MCAP",
             "fixture": ROOT / "tests" / "fixtures" / "mcap_calculator_2026-10-28.json",
             "checkpoint": ROOT / "data" / "ratewatch" / "mcap_oracle" / "battery_mcap.jsonl"},
    "rmg": {"id": "184737", "lender": "RMG",
            "fixture": ROOT / "tests" / "fixtures" / "rmg_calculator_2026-10-28.json",
            "checkpoint": ROOT / "data" / "ratewatch" / "mcap_oracle" / "battery_rmg.jsonl"},
}
PROFILES = [(400000, 6.00), (275000, 4.35), (725000, 7.60), (150000, 3.25), (950000, 5.55), (525000, 8.40)]


def case_list(which: str):
    months = []
    if which == "mcap":
        months += [(mo, p) for mo in range(1, 37) for p in (0, 1)]
        months += [(mo, p) for mo in (17, 18, 29, 30, 41, 42, 53, 54, 65, 71, 72, 89, 101, 102)
                   for p in (3, 4)]
        months += [(mo, 5) for mo in range(39, 121, 3)]
        months += [(1, 2), (2, 5), (3, 5), (6, 2), (84, 2), (120, 2), (13, 3), (61, 3)]
    else:
        months += [(mo, 0) for mo in (1, 2, 3, 4, 5, 6, 7, 9, 11, 12, 13, 17, 18, 23, 24, 25, 29, 30,
                                      35, 36, 37, 41, 42, 47, 48, 49, 53, 54, 59, 60, 61, 65, 71, 72,
                                      83, 84, 89, 96, 101, 102, 119, 120)]
        months += [(mo, 2) for mo in (2, 5, 13, 25, 37, 49, 61, 72)]
    out = []
    for mo, pi in months:
        balance, contract = PROFILES[pi]
        out.append({"balance": balance, "contract": contract, "rem_months": mo,
                    "payment": round(monthly_payment(balance, contract, 300), 2)})
    return out


class Calculator:
    def __init__(self, inst_id):
        self.id = inst_id
        self.s = requests.Session()
        self.tok = None
        self.posts = 0

    def token(self):
        for _ in range(6):
            try:
                r = self.s.get(f"{BASE}/PrepaymentCalc.aspx?ID={self.id}&lang=en", headers=HDR, timeout=90)
                m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text)
                if m:
                    self.tok = m.group(1)
                    return True
            except Exception:
                pass
            time.sleep(6)
        return False

    def ask(self, c):
        if self.tok is None or self.posts >= 25:
            if not self.token():
                return None
            self.posts = 0
        years, months = divmod(c["rem_months"], 12)
        if months == 12:
            years, months = years + 1, 0
        data = {"Input.Balance": str(c["balance"]), "Input.Years": str(years), "Input.Months": str(months),
                "Input.Frequency": "12", "Input.PaymentAmount": str(c["payment"]),
                "Input.CurrentRatePercent": f"{c['contract']:.2f}", "__RequestVerificationToken": self.tok}
        for attempt in range(4):
            try:
                r = self.s.post(f"{BASE}/Prepayment?ID={self.id}&lang=en", data=data, headers=HDR, timeout=90)
                txt = H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)))
                amts = [float(a.replace("$", "").replace(",", ""))
                        for a in re.findall(r"\$\s*[\d,]+\.\d{2}", txt)]
                reinv = re.search(r"reinvestment rate.*?(\d+\.\d{2})%", txt)
                if len(amts) >= 3 and reinv:
                    self.posts += 1
                    return {"reinvestment": float(reinv.group(1)), "three_month": amts[0],
                            "ird": amts[1], "charge": amts[2]}
            except Exception:
                pass
            self.tok = None
            if not self.token():
                return None
            self.posts = 0
            time.sleep(4 * (attempt + 1))
        return None


def run(which: str):
    cfg = INSTANCES[which]
    calc = Calculator(cfg["id"])
    cases = case_list(which)
    done = {}
    ck = cfg["checkpoint"]
    if ck.exists():
        for line in ck.read_text().splitlines():
            rec = json.loads(line)
            done[(rec["balance"], rec["contract"], rec["rem_months"])] = rec
    ck.parent.mkdir(parents=True, exist_ok=True)
    with open(ck, "a") as f:
        for c in cases:
            key = (c["balance"], c["contract"], c["rem_months"])
            if key in done:
                continue
            ans = calc.ask(c)
            if ans is None:
                print(f"{which} {key}: no answer after retries (left for a re-run)", flush=True)
                continue
            rec = {**c, **ans}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[key] = rec
            if len(done) % 25 == 0:
                print(f"{which}: {len(done)}/{len(cases)} recorded", flush=True)
            time.sleep(1.5)
    blob = {"lender": cfg["lender"],
            "source": f"{cfg['lender']}'s online prepayment calculator (ppcalculators.com instance "
                      f"{cfg['id']}, linked from the lender's own site), answers recorded by "
                      f"tools/record_mcap.py",
            "recorded": date.today().isoformat(),
            "cases": [done[(c["balance"], c["contract"], c["rem_months"])] for c in cases
                      if (c["balance"], c["contract"], c["rem_months"]) in done]}
    cfg["fixture"].write_text(json.dumps(blob, indent=1))
    print(f"{which}: wrote {cfg['fixture']} with {len(blob['cases'])}/{len(cases)} cases")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    for w in ("mcap", "rmg") if which == "both" else (which,):
        run(w)
