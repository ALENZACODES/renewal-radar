from datetime import date
from decimal import Decimal as D

import pymupdf
import pytest
from fastapi.testclient import TestClient

from renewal.documents.checks import run_checks
from renewal.documents.fields import FieldHit, extract_fields, required_missing
from renewal.documents.lenders import identify
from renewal.documents.statement import read_statement, read_text
from renewal.documents.text import AcquiredText, OcrUnavailable, PageText, acquire, sniff

TODAY = date(2026, 10, 12)
EN = """RBC Royal Bank
Mortgage Renewal Statement
Mortgage account number: 0123 4567 8901
Outstanding principal balance: $412,345.67
Current interest rate: 5.29%
Renewal offer rate: 4.84%
Term: 5-year fixed
Maturity date: March 1, 2027
Remaining amortization: 19 years 6 months
Regular monthly payment: $2,868.60
Payment frequency: Monthly
"""
FR = """Desjardins
Avis de renouvellement hypothécaire
Numéro de prêt : 81234567
Solde du capital : 450 000,00 $
Taux d'intérêt actuel : 5,49 %
Nouveau taux : 4,79 %
Date d'échéance : 1er mars 2027
Durée du terme : 3 ans
Amortissement restant : 22 ans
Versement mensuel : 2 950,12 $
Type de taux : fixe
"""
TABLE = """TD Canada Trust
Principal balance outstanding      Interest rate      Maturity date
$300,000.00                        4.99%              2027-06-01
"""


def pages(text, method='text_layer'):
    return (PageText(1, text, method),)


def reading(text, method='text_layer'):
    return read_text(AcquiredText(pages(text, method), 'pdf', None), TODAY)


def pdf(text):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


class FakeOcr:
    name = 'fake'

    def __init__(self, text):
        self.text, self.calls = text, 0

    def image_to_text(self, image_png, languages):
        assert image_png.startswith(b'\x89PNG') and 'fra' in languages
        self.calls += 1
        return self.text


def test_english_statement():
    r = reading(EN)
    f = {k: h.value for k, h in r.fields.items()}
    assert f['balance'] == D('412345.67') and f['rate_pct'] == D('5.29')
    assert f['renewal_rate_pct'] == D('4.84') and f['maturity_date'] == date(2027, 3, 1)
    assert f['term_months'] == 60 and f['amortization_months'] == 234
    assert f['payment'] == D('2868.60') and f['frequency'] == 'monthly'
    assert r.lender.code == 'rbc' and r.missing == []
    assert r.redactions == 1 and '0123 4567' not in r.preview[0]['text']
    assert {c.code: c.status for c in r.checks}['payment_consistent'] == 'pass'


def test_french_ocr_statement_goes_to_review():
    r = reading(FR, 'ocr')
    f = {k: h.value for k, h in r.fields.items()}
    assert f['balance'] == D('450000.00') and f['rate_pct'] == D('5.49')
    assert f['maturity_date'] == date(2027, 3, 1) and f['term_months'] == 36
    assert f['rate_type'] == 'fixed' and r.lender.code == 'desjardins'
    assert r.fields['balance'].language == 'fr'
    assert set(r.review) >= {'balance', 'rate_pct'}   # OCR values always reviewed


def test_values_on_next_line():
    hits = extract_fields(pages(TABLE))
    assert hits['balance'].value == D('300000.00') and hits['balance'].line == 2
    assert hits['balance'].confidence == pytest.approx(0.75)


def test_missing_required_fields():
    hits = extract_fields(pages('Scotiabank\nInterest rate: 5.00%\n'))
    assert set(required_missing(hits)) == {'balance', 'maturity_date', 'term_months'}


def test_payment_inconsistency_flags_review():
    r = reading(EN.replace('$2,868.60', '$3,868.60'))
    check = {c.code: c for c in r.checks}['payment_consistent']
    assert check.status == 'warn' and 'payment' in r.review


def hit(name, value):
    return FieldHit(name, value, 1, 1, '', 'en', 0.9)


def test_checks_maturity_and_term():
    checks = run_checks({'maturity_date': hit('maturity_date', date(2025, 1, 1)),
                         'term_months': hit('term_months', 120),
                         'amortization_months': hit('amortization_months', 60),
                         'rate_pct': hit('rate_pct', D('5')), 'renewal_rate_pct': hit('renewal_rate_pct', D('5'))},
                        TODAY)
    codes = {c.code: c.status for c in checks}
    assert codes == {'maturity_past': 'warn', 'term_exceeds_amortization': 'fail', 'rate_duplicate': 'warn'}
    far = run_checks({'maturity_date': hit('maturity_date', date(2040, 1, 1))}, TODAY)
    assert far[0].code == 'maturity_far'


def test_lender_letterhead_beats_body_mention():
    text = 'Scotiabank\nYour mortgage\n' + '\n' * 10 + 'Compare with TD and RBC offers\n'
    assert identify(pages(text)).code == 'scotia'
    assert identify(pages('no lender here')) is None
    assert identify(()) is None


def test_sniff_and_limits():
    assert sniff(b'%PDF-1.7') == 'pdf' and sniff(b'\x89PNG\r\n') == 'png'
    assert sniff(b'\xff\xd8\xff\xe0') == 'jpeg'
    with pytest.raises(ValueError):
        sniff(b'GIF89a')
    with pytest.raises(ValueError):
        acquire(b'%PDF-' + b'0' * (13 * 1024 * 1024))


def test_pdf_text_layer_without_ocr():
    acquired = acquire(pdf(EN))
    assert acquired.pages[0].method == 'text_layer' and not acquired.used_ocr
    assert 'Outstanding principal balance' in acquired.full_text


def test_scanned_pdf_uses_ocr_only_for_empty_pages():
    doc = pymupdf.open()
    doc.new_page()          # blank page stands in for a scan
    data = doc.tobytes()
    doc.close()
    ocr = FakeOcr(EN)
    r = read_statement(data, ocr=ocr, today=TODAY)
    assert ocr.calls == 1 and r.used_ocr and r.ocr_engine == 'fake'
    assert r.fields['balance'].confidence == pytest.approx(0.8)


def test_image_requires_ocr():
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False).tobytes('png')
    with pytest.raises(OcrUnavailable):
        acquire(png)
    r = read_statement(png, ocr=FakeOcr(FR), today=TODAY)
    assert r.lender.code == 'desjardins' and r.used_ocr


def test_bad_pdf():
    with pytest.raises(ValueError):
        acquire(b'%PDF-garbage')


def test_statement_api():
    from renewal import main
    with TestClient(main.app) as c:
        ok = c.post('/api/v5/documents/statement', files={'file': ('s.pdf', pdf(EN), 'application/pdf')})
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body['fields']['balance']['value'] == '412345.67'
        assert body['lender']['code'] == 'rbc'
        bad = c.post('/api/v5/documents/statement', files={'file': ('x.gif', b'GIF89a', 'image/gif')})
        assert bad.status_code == 415
