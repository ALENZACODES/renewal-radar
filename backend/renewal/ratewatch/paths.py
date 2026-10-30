"""Where ratewatch keeps its data. Override with the RATEWATCH_DATA environment variable."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("RATEWATCH_DATA", PROJECT_ROOT / "data" / "ratewatch"))
DATA.mkdir(parents=True, exist_ok=True)
