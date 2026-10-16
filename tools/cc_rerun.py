"""Re-run the Common Crawl pass for every bank, then refresh gap fills and print coverage.

    python tools/cc_rerun.py
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from renewal.ratewatch import backfill as b        # noqa: E402

prog = json.loads(b.PROGRESS.read_text()) if b.PROGRESS.exists() else {}
b.cc_pass(prog)
b.PROGRESS.write_text(json.dumps(prog, indent=1))
b.fill_gaps(prog)
rep = b.report(prog)
for sid, x in rep["banks"].items():
    print(sid, "own", x["covered"], "+ bridged", x["bridged"], "+ BoC", x["boc_typical"], "=", x["covered_with_fills"], flush=True)
