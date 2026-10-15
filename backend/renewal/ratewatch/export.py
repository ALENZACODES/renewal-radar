"""Write the registries to CSV for Excel:  python -m renewal.ratewatch.export  -> sources.csv, checks.csv, ontario_lenders.csv"""
from .paths import DATA as _DATA
import csv, json
from pathlib import Path
from .registry import PRIMARY, CHECKS
from .ontario import ONTARIO

ROOT = _DATA
D = _DATA


def main():
    over = json.loads((D / "url_overrides.json").read_text()) if (D / "url_overrides.json").exists() else {}
    status = {}
    if (D / "linkcheck.csv").exists():
        status = {r["id"]: r["status"] for r in csv.DictReader(open(D / "linkcheck.csv", encoding="utf-8"))}
    with open(ROOT / "sources.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "category", "data", "url", "auto_fixed_url", "method", "ird_method", "fix_from", "status_2026_10_14"])
        for r in PRIMARY:
            w.writerow([*r[:5], over.get(r[0], ""), *r[5:], status.get(r[0], "")])
    with open(ROOT / "checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "validates", "url", "method", "rule", "fix_from", "status_2026_10_14"])
        for r in CHECKS:
            w.writerow([*r, status.get(r[0], "")])
    print("wrote sources.csv, checks.csv; Ontario list is data/ontario_lenders.csv")


if __name__ == "__main__":
    main()
