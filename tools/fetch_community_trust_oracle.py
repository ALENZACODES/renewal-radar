"""Fetch Community Trust's own prepayment-calculator code for the oracle battery.

Community Trust publishes its prepayment penalty calculator at
communitytrust.com/mortgage-pre-payment-penalty-calculator/ — the math lives in the
theme's pages.js (class MortgagePrePaymentPenaltyCalculatorPage), and the current
posted rates it compares against are injected into the page itself as
window.rate_1..rate_5. Both files are saved under data/ratewatch/community_trust_oracle/
for tools/community_trust_oracle.mjs; nothing here is committed (data/ is local by design).

    python tools/fetch_community_trust_oracle.py
"""
import time
from pathlib import Path

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"}
OUT = Path(__file__).resolve().parent.parent / "data" / "ratewatch" / "community_trust_oracle"
FILES = {
    "page.html": "https://communitytrust.com/?p=714",
    "pages.js": "https://communitytrust.com/wp-content/themes/ctc/src/js/pages.js?ver=1780000550",
}


def get(url):
    for i in range(5):
        try:
            r = requests.get(url, headers=H, timeout=60)
            if r.status_code == 200:
                return r.content
            print(url, "->", r.status_code)
        except Exception as exc:
            print(url, type(exc).__name__)
        time.sleep(5 * (i + 1))
    raise SystemExit(f"could not fetch {url}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        data = get(url)
        (OUT / name).write_bytes(data)
        print(f"saved {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
