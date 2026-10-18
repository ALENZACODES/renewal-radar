"""HTTP routes for the broker book review. Stateless: files and deals are processed in memory, nothing is stored."""
from __future__ import annotations

from datetime import date
import math
import threading
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from . import book_ingest, book_review

router = APIRouter(prefix="/api/broker/book", tags=["broker book review"])
MAX_UPLOAD = 20 * 1024 * 1024
MAX_REVIEW_ROWS = 2000
_review_slots = threading.BoundedSemaphore(2)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deals: list[dict] = Field(min_length=1, max_length=MAX_REVIEW_ROWS)
    as_of: date | None = None
    closed_from: date | None = None
    closed_to: date | None = None
    lender: str | None = Field(default=None, max_length=80)
    target_rate: float | None = Field(default=None, gt=0.5, le=15)
    new_term_months: int = Field(default=60, ge=6, le=120)
    fees: float = Field(default=0.0, ge=0, le=50000)

    @field_validator("deals")
    @classmethod
    def validate_records(cls, rows):
        allowed = set(book_ingest.Deal.__dataclass_fields__)
        text_fields = ("deal_id", "borrower", "email", "phone", "lender", "product", "province", "status", "frequency")
        for index, row in enumerate(rows, 1):
            if set(row) - allowed:
                raise ValueError(f"deal {index}: unknown fields; use the import endpoint for external column layouts")
            for name in text_fields:
                value = row.get(name)
                if value is not None and (not isinstance(value, str) or len(value) > 500):
                    raise ValueError(f"deal {index}: invalid {name}")
            for name in ("term_months", "amort_months"):
                value = row.get(name)
                if value is not None:
                    maximum = 480 if name == "amort_months" else 120
                    if isinstance(value, bool):
                        raise ValueError(f"deal {index}: invalid {name}")
                    try:
                        number = float(value)
                    except (TypeError, ValueError, OverflowError):
                        raise ValueError(f"deal {index}: invalid {name}") from None
                    if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= maximum:
                        raise ValueError(f"deal {index}: invalid {name}")
            for name in ("balance", "payment", "contract_rate", "posted_rate", "discount"):
                value = row.get(name)
                if isinstance(value, bool) or isinstance(value, (list, dict)):
                    raise ValueError(f"deal {index}: invalid {name}")
                if isinstance(value, (int, float)) and not math.isfinite(value):
                    raise ValueError(f"deal {index}: non-finite {name}")
            if row.get("review_confirmed") not in (None, True, False) or (
                row.get("review_confirmed") is not None and not isinstance(row["review_confirmed"], bool)
            ):
                raise ValueError(f"deal {index}: review_confirmed must be a boolean")
            evidence = row.get("evidence")
            if evidence is not None and (not isinstance(evidence, dict) or len(evidence) > 30):
                raise ValueError(f"deal {index}: invalid evidence")
            issues = row.get("issues")
            if issues is not None and (
                not isinstance(issues, list) or len(issues) > 40
                or any(not isinstance(message, str) or len(message) > 500 for message in issues)
            ):
                raise ValueError(f"deal {index}: invalid issue list")
        return rows

    @model_validator(mode="after")
    def validate_window(self):
        for value in (self.as_of, self.closed_from, self.closed_to):
            if value is not None and not date(1990, 1, 1) <= value <= date(2100, 12, 31):
                raise ValueError("dates must be between 1990 and 2100")
        if self.closed_from and self.closed_to and self.closed_from > self.closed_to:
            raise ValueError("closed_from must not follow closed_to")
        return self


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file larger than 20 MB")
    return data


@router.post("/import")
async def import_book(file: UploadFile = File(...), mapping: str | None = Form(default=None),
                      date_order: str | None = Form(default=None)):
    """CSV/TSV/semicolon export or JSON list of deals. Optional `mapping` = JSON {field: header} overrides."""
    import json
    try:
        data = await _read(file)
        overrides = json.loads(mapping) if mapping else None
        if overrides is not None and (
            not isinstance(overrides, dict)
            or any(k not in book_ingest.SYNONYMS or not isinstance(v, str) for k, v in overrides.items())
        ):
            raise ValueError("mapping must map known field names to column names")
        if (file.filename or "").lower().endswith(".json") or data.lstrip()[:1] in (b"[", b"{"):
            return await run_in_threadpool(book_ingest.import_json, data, overrides)
        return await run_in_threadpool(book_ingest.import_csv, data, overrides, "csv", date_order)
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(422, str(e))
    finally:
        await file.close()


@router.post("/ocr")
async def ocr_documents(files: list[UploadFile] = File(...), lender: str | None = Form(default=None),
                        closing_date: str | None = Form(default=None), language: str = Form(default="eng")):
    """Mortgage documents (PDF or scans) -> deals via the local OCR. Every OCR deal is flagged for verification."""
    from ..services.document_ocr_v17 import read_mortgage_document
    if language not in ("eng", "fra", "eng+fra", "fra+eng"):
        raise HTTPException(422, "language must be eng, fra, or eng+fra")
    if len(files) > 25:
        raise HTTPException(422, "at most 25 documents per batch")
    out, errors = [], []
    for n, f in enumerate(files, start=1):
        try:
            result = await run_in_threadpool(
                read_mortgage_document, await _read(f), f.filename or f"document-{n}", language
            )
            out.append(book_ingest.deal_from_ocr(result, f"doc-{n}", lender, closing_date))
        except Exception as e:                                   # one bad scan must not sink the batch
            errors.append({"file": Path((f.filename or "document").replace("\\", "/")).name[:120],
                           "error": "Document could not be read; verify its format and size or enter fields manually."})
        finally:
            await f.close()
    return {"deals": out, "errors": errors}


@router.post("/review")
async def review(body: ReviewIn):
    return await run_in_threadpool(_run_review, body)


def _run_review(body: ReviewIn):
    if not _review_slots.acquire(blocking=False):
        raise HTTPException(429, "Two reviews are already running; retry shortly.", headers={"Retry-After": "2"})
    try:
        return book_review.review_book(body.deals, body.as_of, body.closed_from, body.closed_to, body.lender,
                                       body.target_rate, body.new_term_months, body.fees)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "Review inputs are inconsistent; confirm the imported fields.") from exc
    finally:
        _review_slots.release()


@router.post("/review.csv")
async def review_csv(body: ReviewIn):
    rv = await run_in_threadpool(_run_review, body)
    return Response(book_review.to_csv(rv), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="book-opportunities.csv"', "Cache-Control": "no-store"})


@router.get("/offers")
async def offers(term_months: int = 60):
    if term_months not in (6, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120):
        raise HTTPException(422, "unsupported mortgage term")
    return {"offers": book_review.best_offers(term_months)}


@router.get("/capabilities")
async def capabilities():
    return {
        "maximum_import_bytes": MAX_UPLOAD,
        "maximum_import_rows": book_ingest.MAX_ROWS,
        "maximum_review_rows": MAX_REVIEW_ROWS,
        "date_orders": ["day_first", "month_first"],
        "payment_frequencies": sorted(set(book_ingest.values.FREQUENCIES.values())),
        "fields": list(book_ingest.Deal.__dataclass_fields__),
        "requires_ocr_confirmation": True,
        "stores_imported_deals": False,
    }


@router.get("/sample.csv")
async def sample_csv():
    """Fictional sample export (made-up names and numbers) showing a typical broker-software layout."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "fixtures" / "broker-book-sample.csv"
    return Response(p.read_text(encoding="utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="broker-book-sample.csv"'})
