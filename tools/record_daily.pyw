"""Windowless entry point for the scheduled task (run with pythonw.exe: no console window to close by accident).
Every failure, including import errors, is written to data/ratewatch/recorder_logs/ so nothing fails silently."""
import sys, traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "ratewatch" / "recorder_logs"
sys.path.insert(0, str(ROOT / "backend"))


def _fatal(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / f"{datetime.now():%Y-%m}.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


try:
    from renewal.ratewatch import recorder
    recorder.run()
except SystemExit:
    raise
except BaseException:
    _fatal("recorder crashed:\n" + traceback.format_exc())
    sys.exit(1)
