"""Download the prepayment-calculator code of lenders whose calculator ships inside a web-app bundle (ATB, Haventree,
Laurentian, Equitable, Bridgewater). Used only as backtest answer keys; never committed or redistributed.

    python tools/fetch_web_app_oracles.py

Bundle file names carry build hashes, so each calculator page is read and the script holding the calculator's own
code is picked by a string that only that code contains (the same string its harness in tools/*_oracle.mjs cuts at).
"""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent.parent / "data" / "ratewatch"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"}


def get(url):
    r = requests.get(url, headers=H, timeout=60)
    r.raise_for_status()
    return r


def save(folder, name, content):
    out = ROOT / folder
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(content)
    print("saved", out / name, len(content), "bytes")


def find_script(page_url, marker):
    """The page's scripts (and the chunks they reference) searched for the calculator code."""
    html = get(page_url).text
    seen, queue = set(), [urljoin(page_url, s) for s in re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html)]
    queue += [urljoin(page_url, s) for s in re.findall(r'"(/_next/static/chunks/[^"]+\.js)"', html)]
    while queue and len(seen) < 150:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            body = get(u).content
        except requests.RequestException:
            continue
        if marker.encode() in body:
            return body
        text = body.decode("utf-8", "replace")
        queue += [urljoin(page_url, "/_next/" + s) for s in re.findall(r'"(static/chunks/[^"]+\.js)"', text)]
    raise SystemExit(f"calculator code not found from {page_url}: the page has changed")


failed = []
jobs = [
    ("atb", lambda: (save("atb_oracle", "mpp-calculator.app.js", get("https://www.atb.com/static/mppc/js/mpp-calculator.app.js").content),
                     save("atb_oracle", "mpp-calculator.chunk-vendors.js", get("https://www.atb.com/static/mppc/js/mpp-calculator.chunk-vendors.js").content),
                     save("atb_oracle", "GetMppcRates.json", get("https://www.atb.com/atbapi/calculatordata/GetMppcRates?rateType=Posted%20Rates").content))),
    ("haventree", lambda: save("haventree_oracle", "mortgage-calculator-chunk.js",
                               find_script("https://www.haventreebank.com/en-CA/mortgages/pre-payment-calculator", "MortgageCalculator"))),
    ("laurentian", lambda: save("laurentian_oracle", "calculator-chunk.js",
                                find_script("https://www.laurentianbank.ca/en/personal/mortgages/prepayment-penalty-calculator", "fixedRateForm"))),
    ("equitable", lambda: save("equitable_oracle", "calculator-chunk.js",
                               find_script("https://www.eqbank.ca/residential/calculator", "maturityDate:n,inceptionDate:a"))),
    ("bridgewater", lambda: (save("bridgewater_oracle", "bwb-module.js", get("https://amaabcainternal.blob.core.windows.net/bwb/prod/bwb-module.js").content),
                             save("bridgewater_oracle", "bondrate-current.json", get("https://ama.ab.ca/api/bondrate/current").content))),
]
only = set(sys.argv[1:])
for name, job in jobs:
    if only and name not in only:
        continue
    try:
        job()
    except (SystemExit, requests.RequestException) as e:
        print(f"{name}: {e}")
        failed.append(name)
if failed:
    raise SystemExit(f"not fetched: {', '.join(failed)}")
