"""RBC's public Mortgage Prepayment Charge Calculator as a test oracle (it runs on RBC's server, so it is queried,
politely, rather than executed). One case = 4 page requests; cases are spaced PACE seconds apart.

    python tools/rbc_oracle.py cases.json > results.json
    case: {balance, maturity "dd/mm/yyyy", frequency "Monthly", payment, last_payment "dd/mm/yyyy", rate, discount}
"""
import json, re, sys, time
import requests
from bs4 import BeautifulSoup

B = "https://www.rbcroyalbank.com/cgi-bin/mortgage/tools/prepayment/prepayment-charge-calculator.cgi/"
PACE = 15
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
MONEY = r"\$([\d,]+\.\d\d)"


def run_case(c):
    s = requests.Session()
    s.headers.update(UA)
    s.get(B + "overview", timeout=40)
    s.post(B + "overview", data={"_rm": "process"}, timeout=40)
    r = s.post(B + "start", data={"howMuchMortgage": "full", "PrepayCharge": "", "mortgageType": "Fixed", "_rm": "process"},
               timeout=40)
    form = BeautifulSoup(r.text, "html.parser").find("form")
    data = [(i.get("name"), i.get("value")) for i in form.find_all("input", type="hidden")]
    data += [("CurrentMortgageBalance", str(c["balance"])), ("TermMaturityDate", c["maturity"]),
             ("RegularPaymentFrequency", c.get("frequency", "Monthly")), ("RegularPaymentAmount", str(c["payment"])),
             ("DateLastRegularPayment", c["last_payment"]), ("CurrentInterestRate", str(c["rate"])),
             ("DiscountRate", str(c["discount"])), ("_rm", "process")]
    r = s.post(B + "details", data=data, timeout=60)
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    charge = re.search(r"Your Results:\s*" + MONEY, text)
    method = re.search(r"Prepayment Charge Method\s*(.+?)\s*Note:", text)
    asof = re.search(r"calculated as at ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    err = None if charge else text[text.find("Mortgage Details"):][:400]
    return {"charge": float(charge.group(1).replace(",", "")) if charge else None,
            "method": method.group(1) if method else None, "as_of": asof.group(1) if asof else None, "error": err,
            "detail": text[text.find("Prepayment Charge Details"):text.find("Mortgage Details", text.find("Prepayment Charge Details"))][:600]}


if __name__ == "__main__":
    cases = json.load(open(sys.argv[1]))
    out = []
    for i, c in enumerate(cases):
        if i:
            time.sleep(PACE)
        try:
            out.append(run_case(c))
        except Exception as e:                       # noqa: BLE001
            out.append({"charge": None, "error": f"{type(e).__name__}: {e}"})
        print(json.dumps(out[-1]), file=sys.stderr, flush=True)
    print(json.dumps(out))
