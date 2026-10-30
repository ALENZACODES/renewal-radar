from renewal.services.report import render_report
from renewal.services.plan import make_plan,create_ics
from renewal.domain.mortgage_math import compare_offers
from renewal.domain.schemas import Mortgage,Offer
from renewal.domain.rules import switch_decision
from pypdf import PdfReader
from io import BytesIO

def test_pdf_text_has_numbers_sources_and_caveats():
    m=Mortgage()
    pdf=render_report(m,compare_offers(m,[Offer(name='Fictional comparator',rate=4.49,term_months=36)],36),switch_decision(m))
    reader=PdfReader(BytesIO(pdf))
    text=' '.join(page.extract_text() or '' for page in reader.pages)
    assert '480,000' in text
    assert '5.49%' in text
    assert 'OSFI' in text
    assert 'not' in text.lower()
    assert reader.metadata.title=='Renewal Radar - Mortgage Strategy'

def test_ics_plan():
    tasks=make_plan('2027-03-01')
    assert len(tasks)==8
    assert tasks[-1]['due']=='2027-03-01'
    assert create_ics('2027-03-01').count('BEGIN:VEVENT')==8
