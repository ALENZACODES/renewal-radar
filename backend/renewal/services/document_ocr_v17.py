"""Local scan reading with bounded rendering and the existing semantic auditor."""
from __future__ import annotations

from pathlib import Path
import time

import fitz

from ..ocr.camera import prepare_scan
from ..ocr.engines import TesseractEngine, OCREngineError
from ..ocr.document_semantic_auditor_v16 import create_document_semantic_audit


MAX_BYTES = 15 * 1024 * 1024
FIELD_SCOPES = {
    'balance': ('renewal.balance',),
    'offered_rate': ('renewal.offered_rate',),
    'current_rate': ('original.current_rate', 'original.contract_rate'),
    'term_months': ('renewal.term_months',),
    'amortization_months': ('renewal.amortization_months',),
    'maturity_date': ('original.maturity_date', 'renewal.renewal_date'),
    'frequency': ('renewal.frequency',),
}


def read_mortgage_document(data: bytes, filename: str, language: str = 'eng') -> dict:
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ValueError('Supply a document between 1 byte and 15 MB')
    pages = []
    ocr_pages = []
    warnings = []
    deadline = time.monotonic() + 90

    def recognize(image: bytes, number: int):
        remaining = deadline - time.monotonic()
        if remaining < 2:
            raise OCREngineError('Document OCR exceeded its time budget; split the document')
        scan = prepare_scan(image)
        engine = TesseractEngine(language=language, timeout=min(85, max(1, int(remaining - 3))))
        result = engine.recognize(scan, page=number)
        metadata = result.summary()
        confidence = metadata['mean_word_confidence']
        ocr_pages.append({'page': number, 'provider': result.provider, 'version': result.provider_version,
                          'language': result.language, 'mean_word_confidence': confidence,
                          'warnings': list(result.warnings)})
        if not result.text.strip():
            warnings.append(f'Page {number}: no OCR text detected; enter fields manually')
        pages.append({'page_number': number, 'text': result.text[:25000],
                      'mean_confidence': confidence, 'source_hash': result.source_hash})

    if data.startswith(b'%PDF-'):
        try:
            document = fitz.open(stream=data, filetype='pdf')
        except Exception as exc:
            raise ValueError('Unable to open this PDF') from exc
        try:
            if document.needs_pass:
                raise ValueError('Export an unlocked PDF before reviewing it')
            if not 1 <= document.page_count <= 16:
                raise ValueError('PDF must contain 1 through 16 pages')
            for number, page in enumerate(document, 1):
                text = page.get_text(sort=True)
                if len(text) > 25000:
                    raise ValueError('Page text exceeds its limit; split the document')
                if len(text.strip()) >= 30:
                    pages.append({'page_number': number, 'text': text})
                    continue
                if page.rect.width * page.rect.height * 4 > 12000000:
                    raise ValueError('PDF page dimensions exceed the OCR rendering limit')
                recognize(page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes('png'), number)
        finally:
            document.close()
    else:
        recognize(data, 1)
    if not any(page['text'].strip() for page in pages):
        raise OCREngineError('No readable text detected. Retake the scan or enter the terms manually')
    all_ocr = len(ocr_pages) == len(pages)
    audit = create_document_semantic_audit(pages, filename=filename, min_confidence=0.65 if all_ocr else 0)
    mentions = {mention['id']: mention for mention in audit['mentions']}
    fields = {}
    for field, scopes in FIELD_SCOPES.items():
        for scope in scopes:
            fact = audit['facts'].get(scope)
            if not fact or fact['status'] != 'resolved' or fact['value'] is None:
                continue
            evidence = [mentions[ref] for ref in fact.get('evidence', []) if ref in mentions]
            evidence = [item for item in evidence if item['confidence'] is None or item['confidence'] >= 0.65]
            if not evidence:
                continue
            source = evidence[0]
            fields[field] = {'value': fact['value'], 'page': source['page'],
                             'excerpt': source['excerpt'], 'confidence': 'medium'}
            break
    for field in ('balance', 'offered_rate', 'amortization_months', 'maturity_date'):
        if field not in fields:
            warnings.append(f'No unambiguous {field.replace("_", " ")} found; confirm or enter it manually')
    if ocr_pages:
        warnings.append('OCR is an estimated reading, not a verified contract. Check every number and date against the image.')
    return {'filename': Path(filename.replace('\\', '/')).name[:120], 'pages': len(pages),
            'fields': fields, 'warnings': warnings, 'semantic_audit': audit, 'semantic_error': None,
            'ocr_pages': ocr_pages, 'requires_manual_field_verification': True,
            'document_saved': False, 'raw_ocr_stored': False,
            'preview': [{'page': page['page_number'], 'text': page['text'][:2600]} for page in pages]}
