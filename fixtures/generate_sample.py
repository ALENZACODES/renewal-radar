"""Hypothetical renewal letter from a made-up lender (Maple Bank). Not a real bank or a real offer."""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pathlib import Path
p=Path(__file__).with_name('fictional-renewal-letter.pdf')
c=canvas.Canvas(str(p),pagesize=letter)
c.setTitle('Maple Bank illustrative renewal statement - fictional lender')
c.setAuthor('John Khan')
c.setCreator('John Khan')
def line(y,text,size=11,bold=False):
 c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
 c.drawString(55,y,text)
line(738,'MAPLE BANK  |  ILLUSTRATIVE EXAMPLE',18,True)
line(711,'DEMO ONLY - MAPLE BANK IS A FICTIONAL LENDER - NOT A RATE QUOTE',9,True)
line(670,'MORTGAGE RENEWAL OFFER',16,True)
items=[('Renewal Date: 2027-03-01',610),('Mortgage Balance at Renewal: $480,000.00',582),
 ('Renewal Offer: 5.49% fixed',554),('Current Rate: 4.19%',526),('Term: 3 years',498),
 ('Remaining Amortization: 19 years',470),('Payment Frequency: monthly',442),
 ('Insurance Status: uninsured',414)]
for x,y in items: line(y,x,12)
line(368,'Review payment privileges, transfer conditions, and prepayment penalty methods',10)
line(352,'before accepting this fictional renewal proposal.',10)
line(90,'Fictional content. For demonstration and validation only.',9)
c.showPage()
line(738,'MAPLE BANK EXAMPLE - SAMPLE TERMS CONTINUED',14,True)
line(690,'No identifiable personal, property, account, or contact details appear here.',11)
line(640,'Ask for actual written bank offers and a complete payout statement.',11)
c.save()
print(p)
import fitz
with fitz.open(p) as document:
 document[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(p.with_name('sample-renewal-scan.png'))
