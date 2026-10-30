"""Download CIBC's public prepayment-calculator code used as the backtest answer key (not redistributed in git).

    python tools/fetch_cibc_oracle.py
"""
from pathlib import Path
import requests

URL = "https://www.cibc.com/etc.clientlibs/cibcpublic/clientlibs/calculators/mortgageprepayment.min.js"
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "cibc_oracle"
OUT.mkdir(parents=True, exist_ok=True)
r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
r.raise_for_status()
(OUT / "mortgageprepayment.min.js").write_bytes(r.content)
print("saved", OUT / "mortgageprepayment.min.js", len(r.content), "bytes")
