"""OCR temp directories: context-managed workdirs + stale leftover sweep."""
from __future__ import annotations

import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

OCR_TEMP_PREFIXES = ('rr-ocr-', 'rr-docling-', 'rr-paddleocr-', 'rr-easyocr-', 'rr-rapidocr-')
DEFAULT_MAX_AGE_SEC = 3600


@contextmanager
def ocr_tempdir(prefix: str = 'rr-ocr-') -> Iterator[Path]:
    """TemporaryDirectory that always cleans up (including on exceptions)."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(tmp)


def sweep_stale_ocr_temps(
    *,
    max_age_sec: int = DEFAULT_MAX_AGE_SEC,
    tmp_root: str | Path | None = None,
) -> int:
    """Remove leftover rr-*- OCR dirs older than max_age_sec. Returns count removed."""
    root = Path(tmp_root or tempfile.gettempdir())
    now = time.time()
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        name = entry.name
        if not any(name.startswith(p) for p in OCR_TEMP_PREFIXES):
            continue
        try:
            age = now - entry.stat().st_mtime
            if age < max_age_sec:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed
