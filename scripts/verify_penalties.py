"""Offline lender payout-reference reconciliation.

Usage:
    PYTHONPATH=backend python scripts/verify_penalties.py INPUT.json [OUTPUT.json]

The input should consist exclusively of redacted reference data. Never include
names, addresses, lender account numbers, or document contents in public repos.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from renewal.penalty.verification import ReferenceError, load_cases, save_report, verify_cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Redacted reference-case JSON array')
    parser.add_argument('output', type=Path, nargs='?', help='Optional JSON report destination')
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.input)
        report = verify_cases(cases)
    except (OSError, ValueError, ReferenceError, json.JSONDecodeError) as exc:
        print(f'Verification failed: {exc}', file=sys.stderr)
        return 2
    if args.output:
        save_report(args.output, report)
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, indent=2))
    if any(item['status'] == 'variance' for item in report['results'] if item['eligible_for_accuracy_stats']):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
