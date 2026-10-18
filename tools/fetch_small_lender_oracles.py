"""Download the smaller lenders' public prepayment-calculator code used as backtest answer keys (not redistributed in git).

    python tools/fetch_small_lender_oracles.py
"""
import re
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent / "data" / "ratewatch"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"}


def save(folder, name, url):
    out = ROOT / folder
    out.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers=H, timeout=60)
    r.raise_for_status()
    (out / name).write_bytes(r.content)
    print("saved", out / name, len(r.content), "bytes")


save("desjardins_oracle", "calculateur-indemnites-calculs.js",
     "https://www.desjardins.com/outils/calcul-indemnite-remboursement/js/calculateur-indemnites-calculs.js")
base = "https://www.simplii.com/content/dam/simplii-assets/development/calculators/mortgage-prepayment-calculator/js/"
save("simplii_oracle", "calculator.js", base + "calculator.js")
save("simplii_oracle", "pcf_rules.js", base + "pcf_rules.js")
# Tangerine's script name carries a build hash, so it is read from the calculator page.
page = requests.get("https://www.tangerine.ca/en/personal/borrow/mortgage/mortgage-prepayment-charge-calculator",
                    headers=H, timeout=60).text
m = re.search(r'src="([^"]*mortgagePrePayment-calculator/clientlibs/site[^"]*\.js)"', page)
if not m:
    raise SystemExit("Tangerine calculator page changed: script not found")
save("tangerine_oracle", "mortgagePrePayment-calculator.js", "https://www.tangerine.ca" + m.group(1))
