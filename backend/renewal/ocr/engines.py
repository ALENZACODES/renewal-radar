"""Bounded, local OCR engines with explicit provenance and no fictitious accuracy.

Tesseract is the deployable default. Docling is available as an optional adapter
for layout-rich PDFs; do not import optional ML dependencies on the API hot path.
The boundary intentionally accepts normalized images rather than arbitrary URLs.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
from .tempfiles import ocr_tempdir, sweep_stale_ocr_temps
from typing import Protocol

from PIL import Image

from .camera import PreparedScan, CameraError


class OCREngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRWord:
    text: str
    confidence: float | None
    left: int
    top: int
    width: int
    height: int
    page: int = 1

    def as_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OCRPage:
    text: str
    words: tuple[OCRWord, ...]
    source_hash: str
    provider: str
    provider_version: str
    language: str
    page_number: int
    warnings: tuple[str, ...]

    def summary(self, include_words: bool = False) -> dict:
        result = {
            'text': self.text,
            'source_sha256': self.source_hash,
            'provider': self.provider,
            'provider_version': self.provider_version,
            'language': self.language,
            'page_number': self.page_number,
            'warnings': list(self.warnings),
            'word_count': len(self.words),
        }
        confidences = [word.confidence for word in self.words if word.confidence is not None]
        result['mean_word_confidence'] = round(sum(confidences) / len(confidences), 4) if confidences else None
        if include_words:
            result['words'] = [word.as_json() for word in self.words]
        return result


class OCREngine(Protocol):
    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage: ...


ALLOWED_LANGUAGES = frozenset({'eng', 'fra', 'eng+fra', 'fra+eng'})


def sanitize_language(language: str) -> str:
    if language not in ALLOWED_LANGUAGES:
        raise OCREngineError('Only locally supported English/French OCR languages are accepted.')
    return language


def parse_tesseract_tsv(tsv: str, page: int = 1) -> tuple[OCRWord, ...]:
    lines = tsv.splitlines()
    if not lines:
        return ()
    columns = lines[0].split('\t')
    required = {'text', 'conf', 'left', 'top', 'width', 'height'}
    if not required.issubset(columns):
        raise OCREngineError('OCR engine returned an unexpected TSV structure.')
    words = []
    for line in lines[1:]:
        cells = line.split('\t', len(columns) - 1)
        if len(cells) != len(columns):
            continue
        row = dict(zip(columns, cells))
        content = row['text'].strip()
        if not content:
            continue
        try:
            conf = float(row['conf'])
            confidence = round(max(0.0, min(1.0, conf / 100)), 4) if conf >= 0 else None
            coords = [max(0, int(row[column])) for column in ('left', 'top', 'width', 'height')]
        except (ValueError, TypeError):
            continue
        words.append(OCRWord(content, confidence, *coords, page=page))
    return tuple(words)


class TesseractEngine:
    def __init__(self, executable=None, language='eng', timeout=25, psm=3):
        bundled = Path(__file__).resolve().parents[3] / 'runtime' / 'ocr' / 'tesseract.exe'
        self.executable = executable or os.environ.get('RENEWAL_RADAR_TESSERACT') or (
            str(bundled) if os.name == 'nt' and bundled.is_file() else 'tesseract')
        self.language = sanitize_language(language)
        self.timeout = timeout
        self.psm = psm
        if not 1 <= timeout <= 120:
            raise OCREngineError('OCR timeout is unsupported.')
        if psm not in (3, 4, 6, 11, 12):
            raise OCREngineError('Unsupported page segmentation mode.')

    def available(self) -> bool:
        return bool(shutil.which(self.executable))

    def version(self) -> str:
        if not self.available():
            return 'unavailable'
        try:
            completed = subprocess.run([self.executable, '--version'], capture_output=True,
                                       text=True, timeout=4, check=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            return completed.stdout.splitlines()[0][:120] if completed.stdout else 'unknown'
        except (OSError, subprocess.TimeoutExpired):
            return 'unknown'

    def _invoke(self, image_path: str, output_type: str) -> str:
        args = [self.executable, image_path, 'stdout', '--psm', str(self.psm),
                '-l', self.language, output_type]
        try:
            completed = subprocess.run(args, capture_output=True, text=True,
                                       timeout=self.timeout, check=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired as exc:
            raise OCREngineError('The OCR engine exceeded its time budget.') from exc
        except OSError as exc:
            raise OCREngineError('OCR binary could not be executed.') from exc
        if completed.returncode:
            raise OCREngineError('OCR engine failed: ' + completed.stderr[:250])
        if len(completed.stdout) > 2_000_000:
            raise OCREngineError('OCR returned more text than allowed.')
        return completed.stdout

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        if not self.available():
            raise OCREngineError('Tesseract is not installed on the server.')
        sweep_stale_ocr_temps()
        if not 1 <= page <= 100:
            raise OCREngineError('Invalid document page.')
        with ocr_tempdir('rr-ocr-') as tmpdir:
            filename = tmpdir / 'image.png'
            filename.write_bytes(scan.normalized_image)
            text = self._invoke(str(filename), 'txt').strip()
            tsv = self._invoke(str(filename), 'tsv')
        words = parse_tesseract_tsv(tsv, page)
        warnings = []
        if not text:
            warnings.append('no_text_detected')
        if scan.quality and scan.quality.overall < .35:
            warnings.append('poor_scan_quality')
        if words and sum(word.confidence or 0 for word in words) / len(words) < .60:
            warnings.append('low_ocr_word_confidence')
        return OCRPage(text, words, scan.source_sha256, 'tesseract',
                       self.version(), self.language, page, tuple(warnings))


class DoclingEngine:
    """Optional PDF/layout extractor based on the upstream Docling public API.

    Explicitly choose this backend after installing and pinning a reviewed
    Docling build. Its weights may download during initialization; production
    deployments should preinstall all models and disable egress by default.
    """
    def __init__(self, language='eng'):
        self.language = sanitize_language(language)

    def available(self) -> bool:
        try:
            import docling.document_converter  # noqa: F401
            return True
        except ImportError:
            return False

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        if not self.available():
            raise OCREngineError('Docling is an optional dependency and is not installed.')
        try:
            from docling.document_converter import DocumentConverter
            with ocr_tempdir('rr-docling-') as folder:
                path = folder / 'camera.png'
                path.write_bytes(scan.normalized_image)
                document = DocumentConverter().convert(str(path)).document
                text = document.export_to_markdown()
        except Exception as exc:
            raise OCREngineError('Docling extraction failed; original image remains unchanged.') from exc
        return OCRPage(text[:2_000_000], (), scan.source_sha256, 'docling',
                       'deployment-managed', self.language, page,
                       ('word_level_confidence_unavailable',))


def _paddle_language(language: str) -> str:
    if language.startswith('fra'):
        return 'fr'
    return 'en'


def _flatten_paddle_result(payload) -> list[dict]:
    """Extract text/confidence/boxes from PaddleOCR 2.x or 3.x-style outputs."""
    rows = []
    if payload is None:
        return rows
    if isinstance(payload, dict):
        texts = payload.get('rec_texts') or payload.get('texts') or []
        scores = payload.get('rec_scores') or payload.get('scores') or []
        boxes = payload.get('rec_boxes') or payload.get('dt_polys') or payload.get('boxes') or []
        for index, text in enumerate(texts):
            rows.append({
                'text': str(text),
                'confidence': scores[index] if index < len(scores) else None,
                'box': boxes[index] if index < len(boxes) else None,
            })
        for value in payload.values():
            if isinstance(value, (list, tuple, dict)):
                rows.extend(_flatten_paddle_result(value))
        return rows
    if isinstance(payload, (list, tuple)):
        if len(payload) >= 2 and isinstance(payload[1], (list, tuple)) and payload[1]:
            text_candidate = payload[1][0]
            if isinstance(text_candidate, str):
                rows.append({
                    'text': text_candidate,
                    'confidence': payload[1][1] if len(payload[1]) > 1 else None,
                    'box': payload[0],
                })
                return rows
        for item in payload:
            rows.extend(_flatten_paddle_result(item))
    return rows


def _box_bounds(box) -> tuple[int, int, int, int]:
    try:
        if box is None:
            return 0, 0, 0, 0
        if len(box) == 4 and all(isinstance(value, (int, float)) for value in box):
            left, top, right, bottom = box
            return max(0, int(left)), max(0, int(top)), max(0, int(right - left)), max(0, int(bottom - top))
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        return max(0, int(left)), max(0, int(top)), max(0, int(right - left)), max(0, int(bottom - top))
    except (TypeError, ValueError, IndexError):
        return 0, 0, 0, 0


class PaddleOCREngine:
    """Optional modern OCR adapter for PaddleOCR/PP-OCR deployments.

    PaddleOCR has a much larger dependency and model footprint than Tesseract,
    so the source package exposes an adapter but does not vendor the runtime or
    weights. Deployments that need PP-OCRv6, PP-Structure or PaddleOCR-VL should
    install and pin those packages outside this ZIP, then select this provider.
    """
    def __init__(self, language='eng'):
        self.language = sanitize_language(language)

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except ImportError:
            return False

    def version(self) -> str:
        try:
            import paddleocr
            return str(getattr(paddleocr, '__version__', 'installed'))[:120]
        except ImportError:
            return 'unavailable'

    def _predict(self, path: str):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCREngineError('PaddleOCR is an optional dependency and is not installed.') from exc
        try:
            engine = PaddleOCR(lang=_paddle_language(self.language))
            if hasattr(engine, 'predict'):
                return engine.predict(path)
            return engine.ocr(path, cls=True)
        except Exception as exc:
            raise OCREngineError('PaddleOCR extraction failed; original image remains unchanged.') from exc

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        if not 1 <= page <= 100:
            raise OCREngineError('Invalid document page.')
        with ocr_tempdir('rr-paddleocr-') as tmpdir:
            filename = tmpdir / 'image.png'
            filename.write_bytes(scan.normalized_image)
            raw = self._predict(str(filename))
        rows = _flatten_paddle_result(raw)
        words = []
        for row in rows[:5000]:
            text = str(row.get('text') or '').strip()
            if not text:
                continue
            try:
                confidence = row.get('confidence')
                confidence = round(max(0.0, min(1.0, float(confidence))), 4) if confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            words.append(OCRWord(text, confidence, *_box_bounds(row.get('box')), page=page))
        text = '\n'.join(word.text for word in words).strip()
        warnings = ['paddleocr_optional_runtime']
        if not text:
            warnings.append('no_text_detected')
        if words and sum(word.confidence or 0 for word in words) / len(words) < .60:
            warnings.append('low_ocr_word_confidence')
        return OCRPage(text[:2_000_000], tuple(words), scan.source_sha256, 'paddleocr',
                       self.version(), self.language, page, tuple(warnings))


def _easy_languages(language: str) -> list[str]:
    if language == 'eng+fra':
        return ['en', 'fr']
    if language == 'fra+eng':
        return ['fr', 'en']
    if language == 'fra':
        return ['fr']
    return ['en']


def _flatten_easyocr_result(payload) -> list[dict]:
    rows = []
    if payload is None:
        return rows
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box = item[0]
        text = item[1]
        confidence = item[2] if len(item) > 2 else None
        rows.append({'text': str(text), 'confidence': confidence, 'box': box})
    return rows


class EasyOCREngine:
    """Optional EasyOCR adapter for model-based local OCR fallback."""
    def __init__(self, language='eng', gpu=False):
        self.language = sanitize_language(language)
        self.gpu = bool(gpu)

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401
            return True
        except ImportError:
            return False

    def version(self) -> str:
        try:
            import easyocr
            return str(getattr(easyocr, '__version__', 'installed'))[:120]
        except ImportError:
            return 'unavailable'

    def _predict(self, path: str):
        try:
            import easyocr
        except ImportError as exc:
            raise OCREngineError('EasyOCR is an optional dependency and is not installed.') from exc
        try:
            reader = easyocr.Reader(_easy_languages(self.language), gpu=self.gpu)
            return reader.readtext(path)
        except Exception as exc:
            raise OCREngineError('EasyOCR extraction failed; original image remains unchanged.') from exc

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        if not 1 <= page <= 100:
            raise OCREngineError('Invalid document page.')
        with ocr_tempdir('rr-easyocr-') as tmpdir:
            filename = tmpdir / 'image.png'
            filename.write_bytes(scan.normalized_image)
            rows = _flatten_easyocr_result(self._predict(str(filename)))
        words = []
        for row in rows[:5000]:
            text = str(row.get('text') or '').strip()
            if not text:
                continue
            try:
                confidence = row.get('confidence')
                confidence = round(max(0.0, min(1.0, float(confidence))), 4) if confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            words.append(OCRWord(text, confidence, *_box_bounds(row.get('box')), page=page))
        text = '\n'.join(word.text for word in words).strip()
        warnings = ['easyocr_optional_runtime']
        if not text:
            warnings.append('no_text_detected')
        return OCRPage(text[:2_000_000], tuple(words), scan.source_sha256, 'easyocr',
                       self.version(), self.language, page, tuple(warnings))


def _flatten_rapidocr_result(payload) -> list[dict]:
    rows = []
    if payload is None:
        return rows
    if isinstance(payload, tuple) and payload:
        payload = payload[0]
    if hasattr(payload, 'txts') or hasattr(payload, 'boxes'):
        texts = list(getattr(payload, 'txts', []) or [])
        scores = list(getattr(payload, 'scores', []) or [])
        boxes = list(getattr(payload, 'boxes', []) or [])
        for index, text in enumerate(texts):
            rows.append({
                'text': str(text),
                'confidence': scores[index] if index < len(scores) else None,
                'box': boxes[index] if index < len(boxes) else None,
            })
        return rows
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, (list, tuple)) and len(item) >= 3 and isinstance(item[1], str):
                rows.append({'box': item[0], 'text': item[1], 'confidence': item[2]})
            elif isinstance(item, (list, tuple, dict)):
                rows.extend(_flatten_rapidocr_result(item))
    if isinstance(payload, dict):
        rows.extend(_flatten_paddle_result(payload))
    return rows


class RapidOCREngine:
    """Optional RapidOCR adapter for local ONNX-style OCR deployments."""
    def __init__(self, language='eng'):
        self.language = sanitize_language(language)

    def available(self) -> bool:
        try:
            import rapidocr  # noqa: F401
            return True
        except ImportError:
            return False

    def version(self) -> str:
        try:
            import rapidocr
            return str(getattr(rapidocr, '__version__', 'installed'))[:120]
        except ImportError:
            return 'unavailable'

    def _predict(self, path: str):
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise OCREngineError('RapidOCR is an optional dependency and is not installed.') from exc
        try:
            engine = RapidOCR()
            return engine(path)
        except Exception as exc:
            raise OCREngineError('RapidOCR extraction failed; original image remains unchanged.') from exc

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        if not 1 <= page <= 100:
            raise OCREngineError('Invalid document page.')
        with ocr_tempdir('rr-rapidocr-') as tmpdir:
            filename = tmpdir / 'image.png'
            filename.write_bytes(scan.normalized_image)
            rows = _flatten_rapidocr_result(self._predict(str(filename)))
        words = []
        for row in rows[:5000]:
            text = str(row.get('text') or '').strip()
            if not text:
                continue
            try:
                confidence = row.get('confidence')
                confidence = round(max(0.0, min(1.0, float(confidence))), 4) if confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            words.append(OCRWord(text, confidence, *_box_bounds(row.get('box')), page=page))
        text = '\n'.join(word.text for word in words).strip()
        warnings = ['rapidocr_optional_runtime']
        if not text:
            warnings.append('no_text_detected')
        return OCRPage(text[:2_000_000], tuple(words), scan.source_sha256, 'rapidocr',
                       self.version(), self.language, page, tuple(warnings))


class AutoOCREngine:
    """Best-effort OCR router that degrades to a warning-only page.

    This provider is meant for demos and resilient ingestion workflows. It never
    pretends OCR succeeded: if no runtime is available or every runtime fails,
    it returns an empty OCRPage with explicit warnings so V10/V11 review can
    surface missing fields instead of losing the whole request to an exception.
    """
    def __init__(self, language='eng',
                 order: tuple[str, ...] = ('paddleocr', 'docling', 'easyocr', 'rapidocr', 'tesseract')):
        self.language = sanitize_language(language)
        self.order = order

    def _candidate(self, name: str) -> OCREngine:
        if name == 'paddleocr':
            return PaddleOCREngine(language=self.language)
        if name == 'docling':
            return DoclingEngine(language=self.language)
        if name == 'easyocr':
            return EasyOCREngine(language=self.language)
        if name == 'rapidocr':
            return RapidOCREngine(language=self.language)
        if name == 'tesseract':
            return TesseractEngine(language=self.language)
        raise OCREngineError('Unknown auto OCR candidate.')

    def recognize(self, scan: PreparedScan, *, page: int = 1) -> OCRPage:
        warnings = ['auto_ocr_router']
        for name in self.order:
            engine = self._candidate(name)
            available = getattr(engine, 'available', lambda: True)
            if not available():
                warnings.append(f'{name}_unavailable')
                continue
            try:
                result = engine.recognize(scan, page=page)
                return OCRPage(
                    result.text,
                    result.words,
                    result.source_hash,
                    f'auto:{result.provider}',
                    result.provider_version,
                    result.language,
                    result.page_number,
                    tuple(dict.fromkeys([*warnings, *result.warnings])),
                )
            except OCREngineError as exc:
                warnings.append(f'{name}_failed:{str(exc)[:80]}')
        return OCRPage(
            '',
            (),
            scan.source_sha256,
            'auto:none',
            'no-runtime-available',
            self.language,
            page,
            tuple(dict.fromkeys([*warnings, 'no_ocr_runtime_available', 'no_text_detected'])),
        )


def choose_engine(name: str = 'tesseract', *, language='eng') -> OCREngine:
    if name == 'auto':
        return AutoOCREngine(language=language)
    if name == 'tesseract':
        return TesseractEngine(language=language)
    if name == 'docling':
        return DoclingEngine(language=language)
    if name == 'paddleocr':
        return PaddleOCREngine(language=language)
    if name == 'easyocr':
        return EasyOCREngine(language=language)
    if name == 'rapidocr':
        return RapidOCREngine(language=language)
    raise OCREngineError('Unsupported OCR provider; configure tesseract, docling, paddleocr, easyocr or rapidocr.')


def extract_pages(scans: list[PreparedScan], engine: OCREngine,
                  max_pages: int = 12) -> list[OCRPage]:
    if not 1 <= len(scans) <= max_pages:
        raise OCREngineError('Invalid number of OCR pages.')
    return [engine.recognize(scan, page=index) for index, scan in enumerate(scans, 1)]


def redact_common_identifiers(text: str) -> str:
    """Best-effort masking for diagnostic logs. Do not store raw OCR results in logs."""
    text = re.sub(r'\b\d{3}[- ]?\d{3}[- ]?\d{3}\b', '[REDACTED-9-DIGIT]', text)
    text = re.sub(r'(?i)\b(?:account|loan|transit|mortgage)\s*(?:number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{5,}\b',
                  '[REDACTED-ACCOUNT]', text)
    return text
