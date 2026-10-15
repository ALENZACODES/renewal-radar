"""Read full bounded PDF text for the V16 evidence audit, without persisting it."""
from __future__ import annotations

import fitz

from .document_semantic_auditor_v16 import create_document_semantic_audit
from .semantic_evidence_v16 import DocumentSemanticAuditError


def audit_semantic_pdf(data: bytes, filename: str = "document.pdf") -> dict:
    if not isinstance(data, bytes) or not data.startswith(b"%PDF-"):
        raise DocumentSemanticAuditError("Upload must be a valid PDF")
    if len(data) > 8 * 1024 * 1024:
        raise DocumentSemanticAuditError("PDF exceeds the 8 MB limit")
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentSemanticAuditError("Unable to open this PDF") from exc
    try:
        if document.needs_pass:
            raise DocumentSemanticAuditError("Export an unlocked PDF before reviewing it")
        if not 1 <= document.page_count <= 16:
            raise DocumentSemanticAuditError("PDF must contain 1 through 16 pages")
        pages = []
        for index, page in enumerate(document, 1):
            text = page.get_text(sort=True)
            if len(text) > 25000:
                raise DocumentSemanticAuditError("A PDF page exceeds the text limit; split the document")
            pages.append({"page_number": index, "text": text})
        if not any(page["text"].strip() for page in pages):
            raise DocumentSemanticAuditError("No searchable text found. Supply OCR text or a searchable PDF")
        return create_document_semantic_audit(pages, filename=filename)
    finally:
        document.close()
