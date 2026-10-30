"""Download BMO's public prepayment-calculator bundle used as the backtest answer key (not redistributed in git).
The bundle name carries a build stamp, so it is read from the calculator page each time.

    python tools/fetch_bmo_oracle.py
"""
import re
from pathlib import Path
import requests

PAGE = "https://www.bmo.com/main/personal/mortgages/calculators/prepayment-calculator/"
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "bmo_oracle"
H = {"User-Agent": "Mozilla/5.0"}
OUT.mkdir(parents=True, exist_ok=True)
html = requests.get(PAGE, headers=H, timeout=60).text
m = re.search(r'src="(/dist/scripts/main/personal/mortgages/calculators/prepayment-calculator/app[^"]+\.js)"', html)
if not m:
    raise SystemExit("BMO calculator page changed: app bundle not found")
r = requests.get("https://www.bmo.com" + m.group(1), headers=H, timeout=120)
r.raise_for_status()
(OUT / "app.js").write_bytes(r.content)
print("saved", OUT / "app.js", len(r.content), "bytes from", m.group(1))
