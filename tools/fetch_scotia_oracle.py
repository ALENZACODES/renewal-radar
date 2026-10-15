"""Download Scotiabank's public prepayment-calculator files used as the backtest answer key (not redistributed in git).

    python tools/fetch_scotia_oracle.py
"""
from pathlib import Path
import requests

BASE = "https://dmts.scotiabank.com/tools/prepayment/common/"
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "scotia_oracle"
OUT.mkdir(parents=True, exist_ok=True)
for name in ("script/main.js", "data/termRates.json"):
    r = requests.get(BASE + name, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    (OUT / Path(name).name).write_bytes(r.content)
    print("saved", OUT / Path(name).name, len(r.content), "bytes")
