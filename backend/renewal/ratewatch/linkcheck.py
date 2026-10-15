"""Health-check every URL in the registry.  python -m renewal.ratewatch.linkcheck

Status meanings
  OK        200 and content looks right
  REDIRECT  works but moved (update the URL to final_url)
  BLOCKED   401/403/429 or bot wall - site is alive, needs browser mode (playwright) or slower pace
  JS        200 but no rates in raw HTML - rates are loaded by JavaScript; use browser mode / network sniffing
  DEAD      404/410/DNS error - go to fix_from and rediscover (python -m renewal.ratewatch.discover <id>)
"""
from .paths import DATA as _DATA
import csv, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from .registry import PRIMARY, CHECKS

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-CA,en;q=0.9"}
RATE_RE = re.compile(r"\b\d{1,2}\.\d{2,3}\s?%")
OUT = _DATA


def check(row, attempts=3):
    """Triple-checked: a URL is only reported DEAD/BLOCKED after 3 tries with back-off."""
    import time
    for i in range(attempts):
        res = _check_once(row)
        if res[2] in ("OK", "REDIRECT", "JS"):
            return res
        time.sleep(2 * (i + 1))
    return res


def _check_once(row):
    rid, url, method = row[0], row[4] if len(row) == 8 else row[3], row[5] if len(row) == 8 else row[4]
    try:
        if "getDataFromVectors" in url:
            r = requests.post(url, json=[{"vectorId": 80691335, "latestN": 1}], headers=UA, timeout=25)
        else:
            r = requests.get(url, headers=UA, timeout=25, allow_redirects=True, stream=method == "zip_csv")
        code, final = r.status_code, r.url
        body = "" if method == "zip_csv" else r.text[:400000]
    except requests.RequestException as e:
        if "SSL" in type(e).__name__:          # Python rejects some incomplete cert chains; Windows curl does not
            from .ontario import _curl
            code, final, body = _curl(url)
            if 200 <= code < 400:
                return rid, url, "OK", code, "via curl (fix the site's cert chain or keep curl fallback)", len(RATE_RE.findall(body))
        return rid, url, "DEAD", "", type(e).__name__, ""
    rates = len(RATE_RE.findall(body))
    if code in (401, 403, 429, 503) or "captcha" in body.lower()[:5000]:
        status = "BLOCKED"
    elif code >= 400:
        status = "DEAD"
    elif final.rstrip("/").split("#")[0] != url.rstrip("/") and not url.startswith(final.rstrip("/")) and "?" not in url:
        status = "REDIRECT"
    elif method.startswith("html") and rates == 0 and len(row) == 8 and row[2] not in ("official", "archive"):
        status = "JS"
    else:
        status = "OK"
    return rid, url, status, code, final if final != url else "", rates


def main():
    rows = [r for r in PRIMARY + CHECKS if len(sys.argv) < 2 or r[0] in sys.argv[1:]]
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(check, rows))
    OUT.mkdir(exist_ok=True)
    with open(OUT / "linkcheck.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "url", "status", "http", "final_url", "rate_strings_found"])
        w.writerows(results)
    tally = {}
    for r in results:
        tally[r[2]] = tally.get(r[2], 0) + 1
        if r[2] != "OK":
            print(f"{r[0]:5} {r[2]:8} {r[3]!s:4} {r[1]}  {('-> ' + r[4]) if r[4] else ''}")
    print(tally)


if __name__ == "__main__":
    main()
