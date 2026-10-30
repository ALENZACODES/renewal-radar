"""Deterministic image-upload, safety and OCR regression tests.

Tesseract execution tests skip only when the binary is missing. No document,
image or personal data is sent over the network by these tests.
"""
import hashlib
import io
import os
import subprocess

import pytest
from PIL import Image, ImageDraw, ImageOps
from fastapi.testclient import TestClient

from renewal.ocr.camera import (
    CameraError, CameraSettings, ImageQuality, PreparedScan,
    assess_quality, decide_recapture, prepare_scan, scans_to_pdf, sniff_image,
)
from renewal.ocr.engines import (
    DoclingEngine, OCRPage, OCRWord, OCREngineError, TesseractEngine,
    choose_engine, extract_pages, parse_tesseract_tsv,
    redact_common_identifiers, sanitize_language,
)
from renewal.main import app


def make_image(width=1200, height=1600, fmt='PNG', message='RENEWAL OFFER 5.49%'):
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, width - 40, height - 40), outline='black', width=5)
    draw.text((65, 100), message, fill='black', stroke_width=1)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def sample():
    return make_image()


@pytest.fixture
def scan(sample):
    return prepare_scan(sample)


def test_png_signature(sample):
    assert sniff_image(sample) == 'PNG'


def test_jpeg_signature():
    assert sniff_image(make_image(fmt='JPEG')) == 'JPEG'


def test_webp_signature():
    assert sniff_image(make_image(fmt='WEBP')) == 'WEBP'


def test_tiff_signature():
    assert sniff_image(make_image(fmt='TIFF')) == 'TIFF'


@pytest.mark.parametrize('payload', [b'', b'GIF89a', b'%PDF-1.7', b'<svg/>', b'PK\x03\x04'])
def test_reject_unsupported_signatures(payload):
    with pytest.raises(CameraError):
        sniff_image(payload)


def test_empty_upload_rejected():
    with pytest.raises(CameraError, match='empty'):
        prepare_scan(b'')


def test_wrong_type_rejected():
    with pytest.raises(CameraError):
        prepare_scan('not-bytes')


def test_forged_png_rejected():
    with pytest.raises(CameraError):
        prepare_scan(b'\x89PNG\r\n\x1a\n' + b'junk')


def test_jpeg_input_accepted():
    result = prepare_scan(make_image(fmt='JPEG'))
    assert result.original_format == 'JPEG'


def test_webp_input_accepted():
    result = prepare_scan(make_image(fmt='WEBP'))
    assert result.original_format == 'WEBP'


def test_tiff_input_accepted():
    result = prepare_scan(make_image(fmt='TIFF'))
    assert result.original_format == 'TIFF'


def test_upload_size_rejected(sample):
    with pytest.raises(CameraError, match='upload'):
        prepare_scan(sample, CameraSettings(max_bytes=10))


def test_pixel_budget_rejected(sample):
    with pytest.raises(CameraError, match='pixel'):
        prepare_scan(sample, CameraSettings(max_pixels=100))


def test_does_not_return_source_bytes(scan):
    assert 'normalized_image' not in scan.metadata()


def test_sha256_source(sample, scan):
    assert scan.source_sha256 == hashlib.sha256(sample).hexdigest()


def test_sha256_processed(scan):
    assert scan.normalized_sha256 == hashlib.sha256(scan.normalized_image).hexdigest()


def test_immutable_scan(scan):
    with pytest.raises((AttributeError, TypeError)):
        scan.source_sha256 = 'changed'


def test_downscaling():
    data = make_image(2800, 800)
    result = prepare_scan(data, CameraSettings(output_width=1000))
    assert result.normalized_size == (1000, 286)
    assert 'downscale_lanczos' in result.transformations


def test_no_upscaling():
    data = make_image(400, 600)
    result = prepare_scan(data)
    assert result.normalized_size == (400, 600)


def test_default_normalized_png(scan):
    assert scan.normalized_image.startswith(b'\x89PNG')


def test_jpeg_output(sample):
    result = prepare_scan(sample, CameraSettings(output_format='JPEG'))
    assert result.normalized_image.startswith(b'\xff\xd8')


def test_exif_transpose():
    img = Image.new('RGB', (400, 700), 'white')
    exif = img.getexif()
    exif[274] = 6
    output = io.BytesIO()
    img.save(output, format='JPEG', exif=exif)
    result = prepare_scan(output.getvalue())
    assert result.original_orientation == 6
    assert result.normalized_size == (700, 400)
    assert 'exif_orientation' in result.transformations


def test_quality_ranges(scan):
    quality = scan.quality
    for field in ('brightness', 'contrast', 'sharpness', 'resolution',
                  'clipped_dark', 'clipped_light', 'overall'):
        assert 0 <= getattr(quality, field) <= 1


def test_quality_returns_reasons_for_small_photo():
    quality = assess_quality(Image.new('RGB', (200, 200), 'white'))
    assert 'low_resolution' in quality.flags
    assert quality.advice


def test_dark_flag():
    quality = assess_quality(Image.new('RGB', (1200, 1300), 'black'))
    assert 'underexposed' in quality.flags


def test_bright_flag():
    quality = assess_quality(Image.new('RGB', (1200, 1300), 'white'))
    assert 'overexposed' in quality.flags


def test_recapture_override(scan):
    recapture = decide_recapture(scan.quality, threshold=1)
    assert recapture['needs_recapture']


def test_recapture_zero_threshold(scan):
    recapture = decide_recapture(scan.quality, threshold=0)
    assert not recapture['needs_recapture']


def test_recapture_invalid_threshold(scan):
    with pytest.raises(CameraError):
        decide_recapture(scan.quality, threshold=-1)


def test_pdf_conversion(scan):
    pdf = scans_to_pdf([scan])
    assert pdf.startswith(b'%PDF')


def test_multipage_pdf(scan):
    import fitz
    pdf = scans_to_pdf([scan, scan, scan])
    with fitz.open(stream=pdf, filetype='pdf') as document:
        assert len(document) == 3


def test_no_pages_fails():
    with pytest.raises(CameraError):
        scans_to_pdf([])


def test_page_limit(scan):
    with pytest.raises(CameraError):
        scans_to_pdf([scan] * 13)


def test_blank_scan_fails():
    with pytest.raises(CameraError):
        scans_to_pdf([PreparedScan(b'')])


@pytest.mark.parametrize('settings', [
    {'max_bytes': 0}, {'max_pixels': -3},
    {'output_width': 5}, {'output_width': 9000},
    {'contrast': 0.1}, {'contrast': 6.0},
    {'min_acceptable_quality': 2},
])
def test_invalid_settings(settings):
    with pytest.raises(CameraError):
        CameraSettings(**settings)


@pytest.mark.parametrize('language', ['eng', 'fra', 'eng+fra', 'fra+eng'])
def test_supported_languages(language):
    assert sanitize_language(language) == language


@pytest.mark.parametrize('language', ['deu', 'eng; rm -rf /', '', 'ENG', 'en'])
def test_reject_other_languages(language):
    with pytest.raises(OCREngineError):
        sanitize_language(language)


def test_engine_selector():
    assert isinstance(choose_engine('tesseract'), TesseractEngine)
    assert isinstance(choose_engine('docling'), DoclingEngine)


def test_reject_unknown_engine():
    with pytest.raises(OCREngineError):
        choose_engine('remote')


def test_tesseract_timeout_invalid():
    with pytest.raises(OCREngineError):
        TesseractEngine(timeout=999)


def test_tesseract_psm_invalid():
    with pytest.raises(OCREngineError):
        TesseractEngine(psm=777)


def test_missing_binary():
    engine = TesseractEngine(executable='/does/not/exist')
    assert not engine.available()
    assert engine.version() == 'unavailable'


def test_ocr_missing_binary(scan):
    with pytest.raises(OCREngineError):
        TesseractEngine(executable='/does/not/exist').recognize(scan)


def test_tsv_parsing():
    tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
           '5\t1\t1\t1\t1\t1\t20\t30\t50\t10\t91\tMortgage\n')
    words = parse_tesseract_tsv(tsv)
    assert len(words) == 1
    assert words[0].text == 'Mortgage'
    assert words[0].confidence == .91
    assert words[0].left == 20


def test_tsv_missing_columns():
    with pytest.raises(OCREngineError):
        parse_tesseract_tsv('text\nA')


def test_tsv_empty():
    assert parse_tesseract_tsv('') == ()


def test_tsv_bad_numbers_ignored():
    tsv = ('text\tconf\tleft\ttop\twidth\theight\n'
           'offer\t???\t1\t2\t3\t4\n')
    assert parse_tesseract_tsv(tsv) == ()


def test_ocr_page_no_fabricated_confidence():
    page = OCRPage('mortgage', (), '123', 'docling', 'version', 'eng', 1, ())
    assert page.summary()['mean_word_confidence'] is None


def test_ocr_words_are_opt_in():
    page = OCRPage('mortgage', (OCRWord('mortgage', .95, 0, 0, 70, 10),),
                   '123', 'tesseract', '5', 'eng', 1, ())
    assert 'words' not in page.summary()
    assert len(page.summary(include_words=True)['words']) == 1


def test_ocr_confidence_average():
    page = OCRPage('mortgage', (OCRWord('x', .5, 0, 0, 1, 1),
                                 OCRWord('y', .9, 0, 0, 1, 1)),
                   '123', 'tesseract', '5', 'eng', 1, ())
    assert page.summary()['mean_word_confidence'] == .7


def test_page_limit_engine(scan):
    with pytest.raises(OCREngineError):
        extract_pages([], TesseractEngine())


def test_identifier_redaction():
    result = redact_common_identifiers('SIN 123-456-789 account number: ABCD12345678')
    assert '123-456-789' not in result
    assert 'ABCD12345678' not in result


def test_document_hash_propagation(scan):
    if not TesseractEngine().available():
        pytest.skip('local OCR not installed')
    result = TesseractEngine().recognize(scan)
    assert result.source_hash == scan.source_sha256
    assert result.provider == 'tesseract'


def test_integration_inspect(sample):
    client = TestClient(app)
    response = client.post('/api/v8/camera/inspect', files={'file': ('scan.png', sample, 'image/png')})
    assert response.status_code == 200, response.text
    assert response.json()['document_saved'] is False


def test_integration_ocr(sample):
    if not TesseractEngine().available():
        pytest.skip('local OCR not installed')
    client = TestClient(app)
    response = client.post('/api/v8/camera/ocr', files={'file': ('scan.png', sample, 'image/png')})
    assert response.status_code == 200, response.text
    assert response.json()['requires_manual_field_verification']


def test_integration_ocr_bad_language(sample):
    client = TestClient(app)
    response = client.post('/api/v8/camera/ocr?language=deu', files={'file': ('scan.png', sample, 'image/png')})
    assert response.status_code == 503


def test_integration_reject_pdf_as_camera(sample):
    client = TestClient(app)
    response = client.post('/api/v8/camera/inspect', files={'file': ('file.pdf', sample, 'application/pdf')})
    assert response.status_code == 415


def test_integration_create_pdf(sample):
    client = TestClient(app)
    response = client.post('/api/v8/camera/pdf',
                           files=[('files', ('a.png', sample, 'image/png'))])
    assert response.status_code == 200, response.text
    assert response.content.startswith(b'%PDF')


def test_integration_multiple_images(sample):
    import fitz
    client = TestClient(app)
    response = client.post('/api/v8/camera/pdf', files=[
        ('files', ('a.png', sample, 'image/png')),
        ('files', ('b.png', sample, 'image/png')),
    ])
    assert response.status_code == 200
    with fitz.open(stream=response.content, filetype='pdf') as doc:
        assert len(doc) == 2


def test_integration_reject_malformed():
    client = TestClient(app)
    response = client.post('/api/v8/camera/inspect',
                           files={'file': ('a.png', b'not a png', 'image/png')})
    assert response.status_code == 422


def test_no_image_bytes_in_metadata(scan):
    assert 'normalized_image' not in repr(scan.metadata())


def test_image_data_stays_local(sample, monkeypatch):
    # The camera processor does not use HTTP clients or external OCR APIs.
    import socket
    def fail(*args, **kwargs):
        raise AssertionError('network access was attempted')
    monkeypatch.setattr(socket, 'create_connection', fail)
    assert prepare_scan(sample).quality is not None


def test_image_pipeline_without_optional_enhancements(sample):
    config = CameraSettings(
        denoise=False,
        autocontrast=False,
        contrast=1,
        sharpness=1,
    )
    processed = prepare_scan(sample, config)
    assert processed.transformations == ()
    assert processed.original_size == processed.normalized_size
    assert processed.normalized_image.startswith(b'\x89PNG')


def test_image_pipeline_with_enhancements(sample):
    config = CameraSettings(
        denoise=True,
        autocontrast=True,
        contrast=1.3,
        sharpness=1.2,
    )
    processed = prepare_scan(sample, config)
    assert 'median_denoise' in processed.transformations
    assert 'autocontrast' in processed.transformations
    assert 'contrast' in processed.transformations
    assert 'sharpness' in processed.transformations
    assert processed.normalized_sha256 != processed.source_sha256
