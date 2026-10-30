"""Scheduled auto-scraper: collect every lender, verify each reading at three levels, publish the verified board.

    PYTHONPATH=backend python -m renewal.ratewatch.autoscrape OUT_DIR

Runs every 6 hours from .github/workflows/scrape-rates.yml. Writes OUT_DIR/published_board.json (what servers
read) and OUT_DIR/history/YYYY-MM-DD.json (the day's latest board), then prints a one-line-per-lender report.

Fails closed: if fewer than MIN_VERIFIED lenders pass level 2, nothing is written, so a broken run never
replaces a good published board. Verification levels are defined in verify.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import live

MIN_VERIFIED = 5


def run(out_dir: Path) -> int:
    board = live._refresh()
    rows = [r for g in ("banks", "credit_unions", "alternative_lenders") for r in board.get(g, [])]
    for r in rows:
        v = r.get("verification") or {}
        checks = " ".join(f"L{c['level']}{'+' if c['ok'] else '-'}" for c in v.get("checks", []))
        print(f"{r['name']:28} {r['tier']:12} level {v.get('level', '-')}/3  {checks}")
    counts = board.get("verified", {})
    print(f"verified: {counts}  anchor: {board.get('anchor')}")
    if counts.get("level2", 0) < MIN_VERIFIED:
        print(f"only {counts.get('level2', 0)} lenders passed level 2 (need {MIN_VERIFIED}); not publishing", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(board, indent=1, sort_keys=True)
    (out_dir / "published_board.json").write_text(text)
    hist = out_dir / "history"
    hist.mkdir(exist_ok=True)
    (hist / f"{board['refreshed_at'][:10]}.json").write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1] if len(sys.argv) > 1 else "published")))
