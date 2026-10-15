"""Central bounded upload intake: size, magic sniff, page/pixel limits."""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, UploadFile

# ~15 MiB hard cap for streamed uploads (OCR / documents / camera).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
MAX_PDF_PAGES = 20
MAX_IMAGE_PIXELS = 25_000_000
READ_TIMEOUT_HINT_SEC = 60  # documented budget; Starlette has no native stream timeout

Kind = Literal['pdf', 'png', 'jpeg']


@dataclass(frozen=True)
class IngestedUpload:
    data: bytes
    kind: Kind
    filename: str
    pages: int | None = None
    pixels: int | None = None


def sniff_pdf_png_jpeg(data: bytes) -> Kind:
    if data.startswith(b'%PDF-'):
        return 'pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    raise HTTPException(415, 'Only PDF, PNG, or JPEG uploads are accepted.')


async def read_upload_capped(
    upload: UploadFile,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> bytes:
    """Stream an upload into memory with a hard byte ceiling (413 when exceeded)."""
    if max_bytes <= 0 or max_bytes > MAX_UPLOAD_BYTES:
        max_bytes = MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f'Upload must be smaller than {max_bytes // (1024 * 1024)} MB.',
            )
        chunks.append(chunk)
    data = b''.join(chunks)
    if not data:
        raise HTTPException(422, 'Upload is empty.')
    return data


def _pdf_page_count(data: bytes) -> int:
    import pymupdf as fitz

    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as exc:
        raise HTTPException(422, 'Unable to open this PDF.') from exc
    try:
        if doc.needs_pass:
            raise HTTPException(422, 'Password-protected PDFs cannot be read.')
        return int(doc.page_count)
    finally:
        doc.close()


def _image_pixels(data: bytes, kind: Kind) -> int:
    from PIL import Image, UnidentifiedImageError

    previous = Image.MAX_IMAGE_PIXELS
    # Align Pillow's bomb check with our budget; always restore afterward.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            width, height = img.size
            pixels = int(width) * int(height)
            if pixels > MAX_IMAGE_PIXELS:
                raise HTTPException(413, 'Image exceeds the allowed pixel budget.')
            if kind == 'png' and img.format not in (None, 'PNG'):
                raise HTTPException(415, 'PNG signature does not match decoded format.')
            if kind == 'jpeg' and img.format not in (None, 'JPEG'):
                raise HTTPException(415, 'JPEG signature does not match decoded format.')
            return pixels
    except HTTPException:
        raise
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, 'Image exceeds the allowed pixel budget.') from exc
    except (UnidentifiedImageError, OSError, ValueError, OverflowError) as exc:
        raise HTTPException(422, 'The image is invalid or could not be decoded.') from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous


async def ingest_document_upload(
    upload: UploadFile,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    max_pages: int = MAX_PDF_PAGES,
    allowed: set[Kind] | None = None,
) -> IngestedUpload:
    """Read, sniff (PDF/PNG/JPEG), and apply page/pixel limits."""
    allowed = allowed or {'pdf', 'png', 'jpeg'}
    data = await read_upload_capped(upload, max_bytes=max_bytes)
    try:
        kind = sniff_pdf_png_jpeg(data)
    except HTTPException:
        raise
    if kind not in allowed:
        raise HTTPException(415, f'{kind.upper()} uploads are not accepted on this endpoint.')
    pages = pixels = None
    if kind == 'pdf':
        pages = _pdf_page_count(data)
        if not 1 <= pages <= max_pages:
            raise HTTPException(422, f'PDF must contain between 1 and {max_pages} pages.')
    else:
        pixels = _image_pixels(data, kind)
    name = (upload.filename or 'upload').replace('\\', '/').split('/')[-1][:120]
    return IngestedUpload(data=data, kind=kind, filename=name, pages=pages, pixels=pixels)
