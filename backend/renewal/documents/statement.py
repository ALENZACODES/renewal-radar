"""End-to-end statement reading: acquire, redact, identify, extract, check."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from .checks import Check, run_checks
from .fields import FieldHit, extract_fields, required_missing
from .lenders import LenderMatch, identify
from .redact import redact
from .text import AcquiredText, OcrEngine, PageText, acquire

REVIEW_BELOW = 0.85    # OCR reads and next-line matches always go to review


@dataclass(frozen=True)
class StatementReading:
    lender: LenderMatch | None
    fields: dict[str, FieldHit]
    missing: list[str]
    review: list[str]
    checks: list[Check]
    pages: int
    used_ocr: bool
    ocr_engine: str | None
    redactions: int
    preview: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'lender': None if self.lender is None else {
                'code': self.lender.code, 'name': self.lender.name, 'evidence': self.lender.evidence},
            'fields': {k: h.as_dict() for k, h in self.fields.items()},
            'missing': self.missing, 'review': self.review,
            'checks': [c.as_dict() for c in self.checks],
            'pages': self.pages, 'used_ocr': self.used_ocr, 'ocr_engine': self.ocr_engine,
            'redactions': self.redactions, 'preview': self.preview,
            'notice': 'Confirm every field before it is used in any calculation.',
        }


def read_text(acquired: AcquiredText, today: date | None = None) -> StatementReading:
    masked: list[PageText] = []
    total = 0
    for page in acquired.pages:
        r = redact(page.text)
        total += r.masked
        masked.append(replace(page, text=r.text))
    pages = tuple(masked)
    hits = extract_fields(pages)
    checks = run_checks(hits, today or date.today())
    flagged = {f for c in checks if c.status != 'pass' for f in c.fields}
    review = sorted({k for k, h in hits.items() if h.confidence < REVIEW_BELOW} | (flagged & hits.keys()))
    return StatementReading(identify(pages), hits, required_missing(hits), review, checks,
                            len(pages), acquired.used_ocr, acquired.ocr_engine, total,
                            [{'page': p.page, 'method': p.method, 'text': p.text[:2000]} for p in pages])


def read_statement(data: bytes, *, ocr: OcrEngine | None = None, today: date | None = None) -> StatementReading:
    return read_text(acquire(data, ocr=ocr), today)
