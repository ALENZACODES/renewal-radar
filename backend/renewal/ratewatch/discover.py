"""Self-healing URL finder. When a lender moves its rate page, find the new one.

    python -m renewal.ratewatch.discover P025            # one registry id
    python -m renewal.ratewatch.discover https://www.scotiabank.com rates   # any site + keyword set

Order of attack (cheapest first):
  1. robots.txt -> every Sitemap: line -> sitemap index -> child sitemaps
  2. /sitemap.xml, /sitemap_index.xml, /en/sitemap.xml guesses
  3. homepage links (anchor text + href)
  4. Wayback CDX prefix search (finds URLs the site used to have, newest first)
Scores each candidate URL by keyword hits and prints the top 15.
"""
import re, sys
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from .linkcheck import UA
from .registry import PRIMARY, CHECKS

KEYWORDS = {
    "rates": ["mortgage-rate", "mortgage_rate", "mortgagerate", "rates/mortgage", "mortgages/rates", "/rates", "posted", "taux-hypothecaire"],
    "historical": ["historical", "history", "past-rates", "archive"],
    "penalty": ["prepayment", "penalty", "pre-payment", "charge-calculator", "ird", "break"],
    "prime": ["prime"],
}
BAD = ["/fr/", "-fr", "careers", "blog/", "/news/", ".pdf", "business", "commercial", "wealth", "insurance", "auto", "credit-card"]


def get(url, timeout=20):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        return r.text if r.ok else ""
    except requests.RequestException:
        return ""


def sitemap_urls(base, cap=40):
    seen, queue, found = set(), [], set()
    for line in get(urljoin(base, "/robots.txt")).splitlines():
        if line.lower().startswith("sitemap:"):
            queue.append(line.split(":", 1)[1].strip())
    queue += [urljoin(base, p) for p in ("/sitemap.xml", "/sitemap_index.xml", "/en/sitemap.xml")]
    while queue and len(seen) < cap:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", get(sm)):
            if loc.endswith(".xml") or "sitemap" in loc.lower():
                queue.append(loc)
            else:
                found.add(loc)
    return found


def homepage_links(base):
    soup = BeautifulSoup(get(base), "lxml")
    return {urljoin(base, a["href"]) for a in soup.find_all("a", href=True)}


def wayback_urls(host):
    try:
        r = requests.get("https://web.archive.org/cdx/search/cdx", timeout=40, headers=UA,
                         params={"url": host + "/*", "output": "json", "fl": "original", "collapse": "urlkey",
                                 "filter": ["statuscode:200", "original:.*(rate|prepay|penalt).*"], "limit": 3000})
        return {row[0] for row in r.json()[1:]}
    except Exception:
        return set()


def score(url, kinds):
    u = url.lower()
    s = sum(3 for k in kinds for w in KEYWORDS[k] if w in u)
    s += 1 if "mortgage" in u else 0
    s -= sum(4 for b in BAD if b in u)
    return s


def discover(base, kinds=("rates",), use_wayback=True):
    host = urlparse(base).netloc
    cands = sitemap_urls(base) | homepage_links(base)
    if use_wayback and len([c for c in cands if score(c, kinds) > 2]) < 3:
        cands |= {u if u.startswith("http") else "https://" + u for u in wayback_urls(host)}
    ranked = sorted({c for c in cands if urlparse(c).netloc.endswith(host.replace("www.", ""))}, key=lambda c: -score(c, kinds))
    return [(score(c, kinds), c) for c in ranked[:15] if score(c, kinds) > 0]


def kinds_for(row):
    text = " ".join(map(str, row)).lower()
    if "historical" in text:
        return ("historical", "rates")
    if "calculator" in text or "penalt" in text or "prepay" in text:
        return ("penalty",)
    if "prime" in text and "mortgage" not in text:
        return ("prime",)
    return ("rates",)


def main():
    arg = sys.argv[1]
    if arg.startswith("http"):
        base, kinds = arg, tuple(sys.argv[2:]) or ("rates",)
    else:
        row = next(r for r in PRIMARY + CHECKS if r[0] == arg)
        url = row[4] if len(row) == 8 else row[3]
        base, kinds = f"{urlparse(url).scheme}://{urlparse(url).netloc}", kinds_for(row)
    print(f"# {arg}  {base}  looking for {kinds}")
    for s, u in discover(base, kinds):
        print(f"{s:3}  {u}")


if __name__ == "__main__":
    main()
