"""Download National Bank's public prepayment-charges calculator (an AEM form) and cut out its own fixed-rate,
full-payout calculation script, used as the backtest answer key (not redistributed in git).

    python tools/fetch_nbc_oracle.py
"""
import codecs
from pathlib import Path
import requests

URL = "https://www.nbc.ca/forms/financing/prepayment-charges-calculator.html"
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "nbc_oracle"
START, END = "var interest = (loanAmountTotalFixed", "// Taux Variable"


def fixed_total_script(html: str) -> str:
    a = html.find(START)
    b = html.find(END, a)
    if a < 0 or b < 0:
        raise SystemExit("National Bank form changed: fixed full-payout script not found")
    s = html[a:b]
    for _ in range(6):                     # the script sits inside several layers of JSON string escaping
        if "\\" not in s:
            break
        s = codecs.decode(s.replace("\/", "/"), "unicode_escape")
    return s

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    (OUT / "prepayment-charges-calculator.html").write_bytes(r.content)
    script = fixed_total_script(r.text)
    (OUT / "fixed_total.js").write_text(script, encoding="utf-8")
    print("saved", OUT / "fixed_total.js", len(script), "chars")
