"""Fictional lender sample PDF generator, suitable for hackathon demos."""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pathlib import Path
p=Path(__file__).with_name('fictional-renewal-letter.pdf')
c=canvas.Canvas(str(p),pagesize=letter)
c.setAuthor("John Khan"); c.setCreator("John Khan")
c.setTitle('Fictional sample mortgage renewal statement - for product testing')
def line(y,text,size=11,bold=False):
 c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
 c.drawString(55,y,text)
line(738,'MAPLE BANK  |  FICTIONAL SAMPLE DOCUMENT',18,True)
line(711,'DEMO ONLY - NOT A REAL FINANCIAL INSTITUTION OR QUOTE',10,True)
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
line(738,'MAPLE BANK - SAMPLE TERMS CONTINUED',15,True)
line(690,'No identifiable personal, property, account, or contact details appear here.',11)
line(640,'Ask for actual written bank offers and a complete payout statement.',11)
c.save()
print(p)
