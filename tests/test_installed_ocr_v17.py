from pathlib import Path
import shutil

import fitz
import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ocr.engines import TesseractEngine, OCREngineError
from renewal.services.document_ocr_v17 import read_mortgage_document


ROOT = Path(__file__).resolve().parents[1]


def _tesseract_ready() -> bool:
    try:
        return TesseractEngine().available()
    except Exception:
        return False


requires_tesseract = pytest.mark.skipif(
    not _tesseract_ready(),
    reason="Tesseract OCR engine is not installed on this runner",
)



@pytest.fixture(scope='module')
def scan_packet():
    if not _tesseract_ready():
        pytest.skip('Tesseract OCR engine is not installed on this runner')
    return read_mortgage_document((ROOT / 'fixtures/rbc-renewal-scan.png').read_bytes(), 'rbc-scan.png')


@requires_tesseract
def test_installed_engine_is_real_and_current():
    engine = TesseractEngine()
    assert engine.available(), 'The packaged OCR engine must be installed for this release gate'
    assert '5.5.3' in engine.version()
    assert Path(shutil.which(engine.executable)).is_file()


@requires_tesseract
def test_real_ocr_reads_rbc_image_rates_dates_and_terms(scan_packet):
    fields = scan_packet['fields']
    assert fields['balance']['value'] == 480000
    assert fields['offered_rate']['value'] == 5.49
    assert fields['term_months']['value'] == 36
    assert fields['amortization_months']['value'] == 228
    assert fields['maturity_date']['value'] == '2027-03-01'
    assert scan_packet['ocr_pages'][0]['mean_word_confidence'] > 0.65
    assert scan_packet['ocr_pages'][0]['provider'] == 'tesseract'
    assert scan_packet['requires_manual_field_verification']
    assert scan_packet['document_saved'] is False
    assert scan_packet['raw_ocr_stored'] is False


@requires_tesseract
def test_real_scan_keeps_source_passages_and_review_requirements(scan_packet):
    assert scan_packet['semantic_audit']['mentions']
    assert all(field['page'] == 1 and field['excerpt'] for field in scan_packet['fields'].values())
    assert any('Check every number' in warning for warning in scan_packet['warnings'])
    assert 'RBC' in scan_packet['preview'][0]['text']


def test_text_pdf_does_not_require_an_ocr_pass():
    result = read_mortgage_document((ROOT / 'fixtures/fictional-renewal-letter.pdf').read_bytes(), 'letter.pdf')
    assert result['ocr_pages'] == []
    assert result['pages'] == 2
    assert result['fields']['offered_rate']['value'] == 5.49


@requires_tesseract
def test_image_only_pdf_uses_real_ocr():
    with fitz.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=(ROOT / 'fixtures/rbc-renewal-scan.png').read_bytes())
        content = document.tobytes()
    result = read_mortgage_document(content, 'scanned-letter.pdf')
    assert result['fields']['balance']['value'] == 480000
    assert result['fields']['offered_rate']['value'] == 5.49
    assert len(result['ocr_pages']) == 1


@requires_tesseract
def test_french_model_is_available_and_bilingual_reading_is_local():
    result = read_mortgage_document((ROOT / 'fixtures/rbc-renewal-scan.png').read_bytes(), 'bilingual.png', 'eng+fra')
    assert result['ocr_pages'][0]['language'] == 'eng+fra'
    assert result['fields']['offered_rate']['value'] == 5.49


def test_missing_engine_is_an_explicit_error_not_invented_fields(monkeypatch):
    monkeypatch.setenv('RENEWAL_RADAR_TESSERACT', str(ROOT / 'runtime/no-such-engine.exe'))
    with pytest.raises(OCREngineError, match='not installed'):
        read_mortgage_document((ROOT / 'fixtures/rbc-renewal-scan.png').read_bytes(), 'scan.png')


@pytest.mark.parametrize('payload', [b'', b'%PDF-corrupt', b'not an image', b'x' * (8 * 1024 * 1024 + 1)], ids=['empty', 'bad_pdf', 'not_image', 'oversize'])
def test_bad_documents_are_rejected(payload):
    with pytest.raises(ValueError):
        read_mortgage_document(payload, 'untrusted.pdf')


def test_oversized_pdf_page_is_rejected_before_raster_allocation():
    with fitz.open() as document:
        document.new_page(width=5000, height=5000)
        data = document.tobytes()
    with pytest.raises(ValueError, match='dimensions'):
        read_mortgage_document(data, 'huge.pdf')


@requires_tesseract
def test_rbc_demo_and_real_ocr_api():
    with TestClient(app) as http:
        demo = http.get('/api/demo').json()
        assert demo['mortgage']['lender'] == 'RBC Royal Bank (illustrative)'
        assert 'Not issued or endorsed by RBC' in demo['notice']
        response = http.post('/api/v17/documents/read?language=eng', files={
            'file': ('rbc.png', (ROOT / 'fixtures/rbc-renewal-scan.png').read_bytes(), 'image/png'),
        })
        assert response.status_code == 200, response.text
        assert response.json()['fields']['offered_rate']['value'] == 5.49
        assert http.post('/api/v17/documents/read?language=deu', files={'file': ('scan.png', b'x', 'image/png')}).status_code == 422
        assert http.post('/api/v17/documents/read', files={'file': ('x.html', b'html', 'text/html')}).status_code == 415
