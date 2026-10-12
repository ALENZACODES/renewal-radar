from pathlib import Path
import pytest
from renewal.services.extract import extract_pdf
ROOT=Path(__file__).resolve().parents[1]

def test_demo_letter_extraction():
    r=extract_pdf((ROOT/'fixtures'/'fictional-renewal-letter.pdf').read_bytes(),'fictional-renewal-letter.pdf')
    assert r.pages==2
    expected={'balance':480000,'offered_rate':5.49,'current_rate':4.19,
       'term_months':36,'amortization_months':228,'maturity_date':'2027-03-01','frequency':'monthly'}
    for key,value in expected.items():
        assert r.fields[key].value==value
        assert r.fields[key].page==1
        assert r.fields[key].excerpt


def test_pdf_magic_bytes():
    with pytest.raises(ValueError,match='valid PDF'):extract_pdf(b'hello','bad.pdf')


def test_no_sensitive_name_from_path():
    r=extract_pdf((ROOT/'fixtures'/'fictional-renewal-letter.pdf').read_bytes(),'../../mystatement.pdf')
    assert r.filename=='mystatement.pdf'
