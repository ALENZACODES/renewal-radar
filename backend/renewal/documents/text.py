"""Page text acquisition from PDFs and images, with pluggable OCR."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pymupdf as fitz

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 20
MIN_TEXT_LAYER_CHARS = 40
OCR_DPI = 300
IMAGE_MAGIC = {b'\x89PNG': 'png', b'\xff\xd8\xff': 'jpeg', b'II*\x00': 'tiff', b'MM\x00*': 'tiff'}


class OcrEngine(Protocol):
    name: str

    def image_to_text(self, image_png: bytes, languages: str) -> str: ...


class OcrUnavailable(RuntimeError):
    """No OCR engine is installed; the caller should ask for a text PDF or manual entry."""


class TesseractEngine:
    """Tesseract through pytesseract, English and French by default."""

    name = 'tesseract'

    def __init__(self) -> None:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as exc:  # module missing or binary not on PATH
            raise OcrUnavailable('Tesseract OCR is not installed') from exc
        self._tess = pytesseract

    def image_to_text(self, image_png: bytes, languages: str) -> str:
        import io
        from PIL import Image, ImageOps
        img = ImageOps.grayscale(Image.open(io.BytesIO(image_png)))
        if img.width < 1500:          # phone crops read better upscaled
            img = img.resize((img.width * 2, img.height * 2))
        return self._tess.image_to_string(img, lang=languages, config='--psm 6')


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    method: str          # 'text_layer' | 'ocr'


@dataclass(frozen=True)
class AcquiredText:
    pages: tuple[PageText, ...]
    kind: str            # 'pdf' | 'image'
    ocr_engine: str | None

    @property
    def full_text(self) -> str:
        return '\n'.join(p.text for p in self.pages)

    @property
    def used_ocr(self) -> bool:
        return any(p.method == 'ocr' for p in self.pages)


def sniff(data: bytes) -> str:
    if data.startswith(b'%PDF-'):
        return 'pdf'
    for magic, kind in IMAGE_MAGIC.items():
        if data.startswith(magic):
            return kind
    raise ValueError('Upload must be a PDF, PNG, JPEG or TIFF file.')


def acquire(data: bytes, *, ocr: OcrEngine | None = None, languages: str = 'eng+fra',
            max_pages: int = MAX_PAGES) -> AcquiredText:
    """Text for every page. OCR is used only for pages with no usable text layer."""
    if len(data) > MAX_BYTES:
        raise ValueError(f'The file exceeds the {MAX_BYTES // (1024 * 1024)} MB limit.')
    kind = sniff(data)
    if kind != 'pdf':
        if ocr is None:
            raise OcrUnavailable('Images need OCR, which is not available on this server.')
        return AcquiredText((PageText(1, ocr.image_to_text(_to_png(data), languages), 'ocr'),),
                            'image', ocr.name)
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as exc:
        raise ValueError('Unable to open this PDF.') from exc
    try:
        if doc.needs_pass:
            raise ValueError('Password-protected PDFs cannot be read; export an unlocked copy.')
        if not 1 <= doc.page_count <= max_pages:
            raise ValueError(f'PDF must contain between 1 and {max_pages} pages.')
        pages: list[PageText] = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text(sort=True)
            if len(text.strip()) >= MIN_TEXT_LAYER_CHARS:
                pages.append(PageText(index, text, 'text_layer'))
            elif ocr is not None:
                png = page.get_pixmap(dpi=OCR_DPI).tobytes('png')
                pages.append(PageText(index, ocr.image_to_text(png, languages), 'ocr'))
            else:
                pages.append(PageText(index, text, 'text_layer'))
        return AcquiredText(tuple(pages), 'pdf', ocr.name if ocr and any(
            p.method == 'ocr' for p in pages) else None)
    finally:
        doc.close()


def _to_png(data: bytes) -> bytes:
    """Normalise any supported image to PNG via PyMuPDF (no Pillow requirement here)."""
    if data.startswith(b'\x89PNG'):
        return data
    pix = fitz.Pixmap(data)
    return pix.tobytes('png')
