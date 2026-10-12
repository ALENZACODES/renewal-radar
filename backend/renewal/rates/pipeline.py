"""Build the tidy posted-rate history from the reference directory.

    PYTHONPATH=backend python -m renewal.rates.pipeline data/reference build/rates

Writes ``posted_rate_history.csv`` (one row per observation, with quality) and
``posted_rate_summary.json`` (per lender and quality counts). Re-running on the
same inputs produces byte-identical output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Sequence

from .models import Observation
from .sources import dedupe, load_reference_dir
from .validate import boc_five_year, classify, quality_report

FIELDS = ['date', 'lender', 'rate_type', 'term_months', 'rate_pct', 'source_id', 'source_url', 'quality']


def build(reference_dir: Path) -> list[Observation]:
    raw = dedupe(load_reference_dir(reference_dir))
    return classify(raw, boc_five_year(raw))


def write(observations: Sequence[Observation], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    history = out_dir / 'posted_rate_history.csv'
    with history.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(o.as_row() for o in observations)
    summary = out_dir / 'posted_rate_summary.json'
    summary.write_text(json.dumps(quality_report(observations), indent=2, sort_keys=True) + '\n',
                       encoding='utf-8')
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (history, summary)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('reference_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    args = parser.parse_args(argv)
    observations = build(args.reference_dir)
    digests = write(observations, args.out_dir)
    print(json.dumps({'observations': len(observations), 'files': digests}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
