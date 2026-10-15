"""Log redaction: mask SIN-shaped and account-like digit runs; never emit raw OCR."""
from __future__ import annotations

import logging
import re

# Canadian SIN: 3-3-3 with optional separators.
_SIN = re.compile(r'(?<!\d)\d{3}[ \-]?\d{3}[ \-]?\d{3}(?!\d)')
# Long digit runs (account / card / transit), allow space/dash grouping.
_ACCOUNT = re.compile(r'(?<![\d$.,])(?:\d[ \-]?){7,}\d(?![\d.,%])')
# Explicit ban phrases if code accidentally logs OCR payloads.
_OCR_DUMP = re.compile(r'(?i)(raw[_ ]?ocr|ocr[_ ]?text|full[_ ]?text)\s*[:=]\s*.{20,}')


def redact_log_text(text: str) -> str:
    if not text:
        return text
    out = _OCR_DUMP.sub(r'\1=[redacted-ocr]', text)
    out = _SIN.sub('[redacted-sin]', out)
    out = _ACCOUNT.sub('[redacted-account]', out)
    return out


class RedactingFilter(logging.Filter):
    """Apply digit/SIN redaction to every log record message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_log_text(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: redact_log_text(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        redact_log_text(a) if isinstance(a, str) else a for a in record.args
                    )
        except Exception:
            # Never break logging.
            pass
        return True


_installed = False


def install_log_redaction(logger_names: tuple[str, ...] = ('renewal_radar', 'renewal', 'uvicorn', 'uvicorn.error')) -> None:
    """Attach RedactingFilter once to root and key app loggers."""
    global _installed
    if _installed:
        return
    filt = RedactingFilter()
    root = logging.getLogger()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
    for name in logger_names:
        log = logging.getLogger(name)
        log.addFilter(filt)
        for handler in log.handlers:
            handler.addFilter(filt)
    _installed = True
