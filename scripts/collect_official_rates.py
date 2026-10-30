"""Operator-invoked official source collector; no user-controlled URL input."""
import argparse
import asyncio
import json
import os
from pathlib import Path

from renewal.intelligence.rate_history import RateArchive
from renewal.pipelines.official_rates import collect_approved_sources,load_source_manifest


def main():
    parser=argparse.ArgumentParser(description='Capture official posted-rate pages using an approved manifest')
    parser.add_argument('--manifest',required=True,help='Operator-reviewed JSON source configuration')
    parser.add_argument('--archive',default=os.environ.get('RR_RATE_ARCHIVE','rates.sqlite3'))
    args=parser.parse_args()
    sources=load_source_manifest(args.manifest)
    output=asyncio.run(collect_approved_sources(RateArchive(args.archive),sources))
    print(json.dumps(output,indent=2))
    return 1 if any(row['status']!='stored' for row in output) else 0


if __name__=='__main__':
    raise SystemExit(main())
