"""Illustrative sample renewal letter labelled RBC. Text name only, no logo. Not an RBC document and not a real offer."""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pathlib import Path
p=Path(__file__).with_name('fictional-renewal-letter.pdf')
c=canvas.Canvas(str(p),pagesize=letter)
c.setTitle('RBC illustrative sample renewal statement, not an RBC document')
c.setAuthor('John Khan')
c.setCreator('John Khan')
def line(y,text,size=11,bold=False):
 c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
 c.drawString(55,y,text)
line(738,'RBC ROYAL BANK  |  ILLUSTRATIVE SAMPLE',18,True)
line(711,'DEMO ONLY  |  NOT ISSUED OR ENDORSED BY RBC  |  NOT A RATE QUOTE',9,True)
line(670,'MORTGAGE RENEWAL OFFER',16,True)
items=[('Renewal Date: 2027-03-01',610),('Mortgage Balance at Renewal: $480,000.00',582),
 ('Renewal Offer: 5.49% fixed',554),('Current Rate: 4.19%',526),('Term: 3 years',498),
 ('Remaining Amortization: 19 years',470),('Payment Frequency: monthly',442),
 ('Insurance Status: uninsured',414)]
for x,y in items: line(y,x,12)
line(368,'Review payment privileges, transfer conditions, and prepayment penalty methods',10)
line(352,'before accepting this illustrative renewal proposal.',10)
line(104,'Illustrative sample for demonstration only. This is not an RBC document.',9)
line(90,'It was not issued or endorsed by RBC, and the terms are not a rate quote.',9)
c.showPage()
line(738,'RBC ILLUSTRATIVE SAMPLE  |  SAMPLE TERMS CONTINUED',14,True)
line(690,'No identifiable personal, property, account, or contact details appear here.',11)
line(640,'Ask for actual written bank offers and a complete payout statement.',11)
line(104,'Illustrative sample for demonstration only. This is not an RBC document.',9)
line(90,'It was not issued or endorsed by RBC, and the terms are not a rate quote.',9)
c.save()
print(p)
import fitz
with fitz.open(p) as document:
 document[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(p.with_name('rbc-renewal-scan.png'))
