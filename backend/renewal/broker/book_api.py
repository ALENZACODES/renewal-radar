"""HTTP routes for the broker book review. Stateless: files and deals are processed in memory, nothing is stored."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import book_ingest, book_review

router = APIRouter(prefix="/api/broker/book", tags=["broker book review"])
MAX_UPLOAD = 20 * 1024 * 1024


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deals: list[dict] = Field(min_length=1, max_length=20000)
    as_of: date | None = None
    closed_from: date | None = None
    closed_to: date | None = None
    lender: str | None = Field(default=None, max_length=80)
    target_rate: float | None = Field(default=None, gt=0.5, le=15)
    new_term_months: int = Field(default=60, ge=6, le=120)
    fees: float = Field(default=0.0, ge=0, le=50000)


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file larger than 20 MB")
    return data


@router.post("/import")
async def import_book(file: UploadFile = File(...), mapping: str | None = Form(default=None)):
    """CSV/TSV/semicolon export or JSON list of deals. Optional `mapping` = JSON {field: header} overrides."""
    import json
    data = await _read(file)
    overrides = json.loads(mapping) if mapping else None
    try:
        if (file.filename or "").lower().endswith(".json") or data.lstrip()[:1] in (b"[", b"{"):
            return book_ingest.import_json(data, overrides)
        return book_ingest.import_csv(data, overrides)
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(422, str(e))


@router.post("/ocr")
async def ocr_documents(files: list[UploadFile] = File(...), lender: str | None = Form(default=None),
                        closing_date: str | None = Form(default=None), language: str = Form(default="eng")):
    """Mortgage documents (PDF or scans) -> deals via the local OCR. Every OCR deal is flagged for verification."""
    from ..services.document_ocr_v17 import read_mortgage_document
    if len(files) > 25:
        raise HTTPException(422, "at most 25 documents per batch")
    out, errors = [], []
    for n, f in enumerate(files, start=1):
        try:
            result = read_mortgage_document(await _read(f), f.filename or f"document-{n}", language)
            out.append(book_ingest.deal_from_ocr(result, f"doc-{n}", lender, closing_date))
        except Exception as e:                                   # one bad scan must not sink the batch
            errors.append({"file": f.filename, "error": str(e)[:200]})
    return {"deals": out, "errors": errors}


@router.post("/review")
async def review(body: ReviewIn):
    return book_review.review_book(body.deals, body.as_of, body.closed_from, body.closed_to, body.lender,
                                   body.target_rate, body.new_term_months, body.fees)


@router.post("/review.csv")
async def review_csv(body: ReviewIn):
    rv = book_review.review_book(body.deals, body.as_of, body.closed_from, body.closed_to, body.lender,
                                 body.target_rate, body.new_term_months, body.fees)
    return Response(book_review.to_csv(rv), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="book-opportunities.csv"', "Cache-Control": "no-store"})


@router.get("/offers")
async def offers(term_months: int = 60):
    return {"offers": book_review.best_offers(term_months)}


@router.get("/sample.csv")
async def sample_csv():
    """Fictional sample export (made-up names and numbers) showing a typical broker-software layout."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "fixtures" / "broker-book-sample.csv"
    return Response(p.read_text(encoding="utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="broker-book-sample.csv"'})
