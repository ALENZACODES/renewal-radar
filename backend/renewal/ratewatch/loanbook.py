"""Size of residential mortgage book per lender - free, exact, monthly, from OSFI M4 balance sheets.

  python -m renewal.ratewatch.loanbook download   fetch the 3 OSFI CSVs (~1.3 GB, banks / trust cos / loan cos)
  python -m renewal.ratewatch.loanbook            -> data/loan_book_osfi.csv  (latest month, $ millions)

Covers every federally regulated bank, trust and loan company (big 6, Equitable, Home Trust, Peoples,
Haventree, ICICI, Manulife, Tangerine is inside Scotiabank, Simplii inside CIBC, etc.).
NOT covered (not OSFI-regulated): credit unions (FSRA / CU annual reports), monolines (First National,
MCAP, RMG, CMLS - use their investor reports: 'mortgages under administration'), MICs/private lenders.
Values on M4 are in $ thousands; balances are on-balance-sheet (securitized-off loans are excluded).
"""
from .paths import DATA as _DATA
import csv, sys
from collections import defaultdict
from pathlib import Path
import requests

D = _DATA
OSFI = "https://open.canada.ca/data/dataset"
FILES = {
    "banks_m4.csv": f"{OSFI}/91ed76b4-a1a2-4f87-9c4c-59cd64f7a9de/resource/d0f6040e-671c-4301-a235-e9e7ba164604/download/banks_monthly_m4.csv",
    "trust_m4.csv": f"{OSFI}/203bb08d-fdff-46f6-93ec-00e5d1d76a81/resource/6c9cfdc2-b3ea-4eb9-b564-fd28e7aba16b/download/trust_companies_monthly_m4.csv",
    "loan_m4.csv": f"{OSFI}/79c99c29-deff-4093-9c55-fde484d20028/resource/d5e1e6e8-c13c-4224-8b22-521a1661a0ee/download/loan_companies_monthly_m4.csv",
}
LINES = {"0540": "res_insured", "0542": "res_uninsured", "0608": "res_reverse", "2117": "non_residential",
         "1076": "heloc_secured_residential"}


def download():
    (D / "osfi").mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        with requests.get(url, stream=True, timeout=600) as r, open(D / "osfi" / name, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def build():
    latest, vals = {}, defaultdict(dict)
    for name in FILES:
        kind = name.split("_")[0]
        with open(D / "osfi" / name, encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            fi_col = rd.fieldnames[3]          # "Total All Banks/..." / "Total Trust Companies/FIs" / "Total Loan Companies/FIs"
            for row in rd:
                code = row["Data Point Address/Adresse de point de donnée"]
                if code not in LINES:
                    continue
                fi = row[fi_col]
                if fi.lower().startswith("total") or row["FI Inactive Date/Date d'inactivité IFF"] != "9999-12-31":
                    continue
                month = row["Calendar Month/Mois civil"]
                key = (kind, fi)
                if month > latest.get(key, ""):
                    latest[key] = month
                    vals[key] = {}
                if month == latest[key]:
                    vals[key][LINES[code]] = float(row["Measure Value/Valeur de mesure"] or 0) / 1000
    out = []
    newest = max(latest.values())
    cutoff = f"{int(newest[:4]) - 1}{newest[4:]}"      # drop institutions that stopped filing (merged/closed)
    for (kind, fi), v in vals.items():
        if latest[(kind, fi)] < cutoff:
            continue
        res = v.get("res_insured", 0) + v.get("res_uninsured", 0) + v.get("res_reverse", 0)
        out.append([fi, kind, latest[(kind, fi)], round(res, 1), round(v.get("res_insured", 0), 1),
                    round(v.get("res_uninsured", 0), 1), round(v.get("res_reverse", 0), 1),
                    round(v.get("heloc_secured_residential", 0), 1), round(v.get("non_residential", 0), 1)])
    out.sort(key=lambda r: -r[3])
    with open(D / "loan_book_osfi.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "type", "as_of", "residential_mortgages_$M", "insured_$M", "uninsured_$M",
                    "reverse_$M", "personal_loans_secured_by_residential_$M", "commercial_mortgages_$M"])
        w.writerows(out)
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["download"]:
        download()
    for r in build()[:60]:
        print(f"{r[0][:48]:48} {r[1]:6} {r[2]}  ${r[3]:>12,.0f}M")
