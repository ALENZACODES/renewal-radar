"""Download TD's public prepayment-calculator files used as the backtest answer key (not redistributed in git).

    python tools/fetch_td_oracle.py
"""
from pathlib import Path
import requests

BASE = "https://ix0.apps.td.com/mortgage-prepayment-calculator/"
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "td_oracle"
OUT.mkdir(parents=True, exist_ok=True)
for name in ("js/td-prepayment.min.js", "previous_rates.txt"):
    r = requests.get(BASE + name, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    (OUT / Path(name).name).write_bytes(r.content)
    print("saved", OUT / Path(name).name, len(r.content), "bytes")
