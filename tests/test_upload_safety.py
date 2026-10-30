"""OCR intake limits, log redaction, CSV formula escape, temp cleanup."""
from __future__ import annotations

import io
import logging
import tempfile
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from renewal.main import app
from renewal.ocr.tempfiles import ocr_tempdir, sweep_stale_ocr_temps
from renewal.ratewatch.extras import csv_safe, to_csv
from renewal.security.log_redact import RedactingFilter, redact_log_text
from renewal.security.uploads import MAX_UPLOAD_BYTES, ingest_document_upload, sniff_pdf_png_jpeg


def _png_bytes(width=64, height=64) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color=(200, 200, 200)).save(buf, format='PNG')
    return buf.getvalue()


def test_sniff_rejects_non_pdf_png_jpeg():
    with pytest.raises(HTTPException) as exc:
        sniff_pdf_png_jpeg(b'GIF89a')
    assert exc.value.status_code == 415


def test_upload_413_and_415(monkeypatch):
    with TestClient(app) as c:
        # 415 wrong type
        r = c.post(
            '/api/documents/extract',
            files={'file': ('x.txt', b'hello world not a pdf', 'text/plain')},
        )
        assert r.status_code == 415
        # 413 oversize (streamed)
        huge = b'%PDF-1.4\n' + b'A' * (MAX_UPLOAD_BYTES + 10)
        r = c.post(
            '/api/documents/extract',
            files={'file': ('huge.pdf', huge, 'application/pdf')},
        )
        assert r.status_code == 413


def test_ingest_image_pixel_budget():
    from PIL import Image
    from renewal.security import uploads as up

    small = _png_bytes(100, 100)
    assert sniff_pdf_png_jpeg(small) == 'png'
    original = up.MAX_IMAGE_PIXELS
    previous_pil = Image.MAX_IMAGE_PIXELS
    up.MAX_IMAGE_PIXELS = 1000
    try:
        with pytest.raises(HTTPException) as exc:
            up._image_pixels(_png_bytes(64, 64), 'png')  # 4096 > 1000
        assert exc.value.status_code == 413
    finally:
        up.MAX_IMAGE_PIXELS = original
        Image.MAX_IMAGE_PIXELS = previous_pil


def test_log_redaction_sin_and_account():
    sample = 'Client SIN 123-456-789 account 1234 5678 9012 balance $480,000.00'
    out = redact_log_text(sample)
    assert '123-456-789' not in out
    assert '1234 5678 9012' not in out
    assert '[redacted-sin]' in out
    assert '[redacted-account]' in out
    assert '$480,000.00' in out
    assert 'raw_ocr=secret long text about mortgages here' not in redact_log_text(
        'raw_ocr=secret long text about mortgages here XXXXXXXXXXX'
    )


def test_log_filter_on_logger():
    log = logging.getLogger('renewal_radar_test_redact')
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    log.addHandler(handler)
    log.info('SIN 123 456 789 and acct 998877665544')
    text = stream.getvalue()
    assert '123 456 789' not in text
    assert '998877665544' not in text


def test_csv_safe_prefixes_formula_cells():
    assert csv_safe('=CMD()') == "'=CMD()"
    assert csv_safe('+1+1') == "'+1+1"
    assert csv_safe('-5.2') == "'-5.2"
    assert csv_safe('@SUM') == "'@SUM"
    assert csv_safe('\tTAB') == "'\tTAB"
    assert csv_safe('\rX') == "'\rX"
    assert csv_safe('normal') == 'normal'
    assert csv_safe(12832.0) == '12832.0'
    csv_text = to_csv({'penalty': 12832.0, 'evil': '=1+1'}, [])
    assert "'=1+1" in csv_text
    assert 'penalty,12832.0' in csv_text


def test_ocr_tempdir_cleans_up():
    with ocr_tempdir('rr-ocr-') as path:
        marker = path / 'x.bin'
        marker.write_bytes(b'hi')
        assert marker.exists()
        kept = path
    assert not kept.exists()


def test_sweep_stale_ocr_temps(tmp_path):
    stale = tmp_path / 'rr-ocr-stale-test'
    stale.mkdir()
    (stale / 'a').write_text('x', encoding='utf-8')
    # backdate mtime
    old = time.time() - 7200
    import os
    os.utime(stale, (old, old))
    fresh = tmp_path / 'rr-ocr-fresh-test'
    fresh.mkdir()
    removed = sweep_stale_ocr_temps(max_age_sec=3600, tmp_root=tmp_path)
    assert removed >= 1
    assert not stale.exists()
    assert fresh.exists()
