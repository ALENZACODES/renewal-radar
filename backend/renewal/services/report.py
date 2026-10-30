"""Self-contained PDF with calculation disclosure and primary-source references."""
from __future__ import annotations
from io import BytesIO
from datetime import datetime,timezone
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak,KeepTogether
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from xml.sax.saxutils import escape
from ..domain.rules import OSFI_MQR,OSFI_SWITCH,RENEWAL,PENALTY,INSURED_SWITCH
from ..domain.schemas import NegotiationRequest
from .negotiation import negotiation_packet
from .plan import make_plan

GREEN=colors.HexColor('#087F5B'); INK=colors.HexColor('#123329'); SMOKE=colors.HexColor('#677C77')

_STY=getSampleStyleSheet()
_STY.add(ParagraphStyle(name='HeroRR',fontName='Helvetica-Bold',fontSize=24,leading=29,textColor=INK,spaceAfter=10))
_STY.add(ParagraphStyle(name='SectionRR',fontName='Helvetica-Bold',fontSize=13,leading=18,textColor=INK,spaceBefore=17,spaceAfter=9))
_STY.add(ParagraphStyle(name='SmallRR',fontName='Helvetica',fontSize=8,leading=12,textColor=SMOKE))
_STY.add(ParagraphStyle(name='BodyRR',fontName='Helvetica',fontSize=10,leading=15,spaceAfter=5))
def _para(s,style): return Paragraph(escape(str(s)),_STY[style])

def render_report(mortgage, analysis, switch, penalty=None, title='Mortgage Renewal Strategy') -> bytes:
    result=BytesIO()
    doc=SimpleDocTemplate(result,pagesize=letter,topMargin=48,bottomMargin=46,leftMargin=52,rightMargin=52,
                          title='Renewal Radar - Mortgage Strategy')
    story=[]
    story.append(_para('RENEWAL RADAR / CANADA','SmallRR'))
    story.append(_para(title,'HeroRR'))
    story.append(_para(f'Prepared {datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")}  |  Educational planning estimate','SmallRR'))
    story.append(Spacer(1,16))
    story.append(_para('Your mortgage at a glance','SectionRR'))
    info=[('Principal balance',f'${mortgage.balance:,.2f}'),('Renewal interest rate',f'{mortgage.offered_rate:.2f}%'),
      ('Proposed term',f'{mortgage.term_months} months'),('Remaining amortization',f'{mortgage.amortization_months} months'),
      ('Payment frequency',mortgage.frequency),('Maturity',mortgage.maturity_date),
      ('Insurance',mortgage.insurance_status)]
    facts=Table([[ _para(x,'BodyRR'),_para(y,'BodyRR')] for x,y in info],colWidths=[220,250],hAlign='LEFT')
    facts.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#E1EAE5')),
       ('BOTTOMPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7)]))
    story.append(facts)
    story.append(_para('Financial comparison','SectionRR'))
    headers=['Offer','Rate','Payment','Interest','End balance','Net cost']
    rows=[headers]
    for sc in analysis['scenarios']:
        rows.append([sc['offer']['name'][:24],f"{sc['offer']['rate']:.2f}%",
           f"${sc['loan']['regular_payment']:,.0f}",f"${sc['loan']['total_interest']:,.0f}",
           f"${sc['loan']['ending_balance']:,.0f}",f"${sc['net_cost']:,.0f}"])
    widths=[115,50,75,76,79,75]
    resulttable=Table(rows,colWidths=widths,repeatRows=1)
    resulttable.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),INK),('TEXTCOLOR',(0,0),(-1,0),colors.white),
       ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),
       ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#EFF7F2')]),
       ('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),
       ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.append(resulttable)
    story.append(Spacer(1,8))
    story.append(_para('All options are compared over a common interval when their term supports that interval. Payment savings are not added to interest savings; they describe different views of the same cash flows. Net cost = all payments + ending loan balance + net fees - starting balance.','SmallRR'))
    story.append(_para('Lender-switch rules','SectionRR'))
    story.append(_para(switch['headline'],'BodyRR'))
    for reason in switch['reasons'] + switch['to_verify']:
        story.append(_para('• '+reason,'BodyRR'))
    story.append(_para(switch['disclaimer'],'SmallRR'))
    if penalty:
        story.append(_para('Early payout sensitivity','SectionRR'))
        story.append(_para(f'Three-month interest proxy: ${penalty["three_month_interest"]:,.2f}. Illustrative IRD: '+
                       (f'${penalty["ird_estimate"]:,.2f}' if penalty['ird_estimate'] is not None else 'unknown'), 'BodyRR'))
        story.append(_para(penalty['disclaimer'],'SmallRR'))
    story.append(_para('Before you decide','SectionRR'))
    for line in ['Confirm an actual written, personalized rate offer, not only a posted rate.',
      'Get your existing lender to confirm discharge penalties, legal fees and any collateral charge or HELOC complications.',
      'Ask the receiving lender for a complete written comparison and underwriting decision.',
      'Confirm mortgage insurer transferability and whether an existing default-insurance certificate carries over.',
      'Compare portability, prepayment options, penalty methodology, term risks and the new maturity date.']:
        story.append(_para('• '+line,'BodyRR'))
    story.append(_para('Personalized lender conversation','SectionRR'))
    if len(analysis['scenarios']) > 1:
        competing=analysis['scenarios'][1]['offer']
        request=NegotiationRequest(mortgage=mortgage,competing_rate=competing['rate'],
             competing_lender=competing['name'],competitor_offer_verified=False)
        packet=negotiation_packet(request)
        story.append(_para('Sample script (hypothetical rate, not verified)', 'SmallRR'))
        for line in packet['call_script']:
            story.append(_para(line,'BodyRR'))
    else:
        story.append(_para('Ask your lender for a written rate, term, fees, and payment schedule before accepting.', 'BodyRR'))
    story.append(_para('Your renewal calendar','SectionRR'))
    for item in make_plan(mortgage.maturity_date):
        story.append(_para(f"{item['due']}  -  {item['title']}: {item['description']}", 'BodyRR'))
    story.append(PageBreak())
    story.append(_para('Evidence and methodology appendix','HeroRR'))
    story.append(_para('Canadian primary sources','SectionRR'))
    for name,url in [('OSFI minimum qualifying rate',OSFI_MQR),('OSFI uninsured straight switches',OSFI_SWITCH),
      ('Finance Canada insured switches',INSURED_SWITCH),('FCAC renewing your mortgage',RENEWAL),
      ('FCAC early repayment and IRD',PENALTY),('Bank of Canada Valet data','https://www.bankofcanada.ca/valet/docs/')]:
        story.append(_para(name+': '+url,'SmallRR'))
        story.append(Spacer(1,5))
    story.append(_para('How we calculate the results','SectionRR'))
    story.append(_para('The fixed-rate payment model uses Canadian nominal semiannual compounding: periodic_rate = (1 + annual_APR / 2) ^ (2 / payments_per_year) - 1. This periodic rate amortizes the selected principal across the outstanding contractual amortization term.', 'BodyRR'))
    story.append(_para('Variable-rate paths are illustrative, assuming nominal monthly compounding and payment recalculation when the modeled rate changes. Fixed-payment variable trigger behavior depends on the actual contract. These scenarios are not forecasts.', 'BodyRR'))
    story.append(_para('Economic cost uses payments over the shared analysis horizon plus remaining loan balance and net fees minus starting mortgage principal. Interest-cost savings and payment savings are not additive. The model distinguishes advertised, personalized and hypothetical rate inputs.', 'BodyRR'))
    story.append(_para('A three-month-interest estimate is only a comparison proxy; lender-specific IRD may use an original posted rate, contract discount, or other formula. Request the lender’s actual written payout and discharge statement.', 'BodyRR'))
    story.append(_para('Verification and limits','SectionRR'))
    for line in ['A lender-switch exemption is conditional, not a guaranteed approval or offered interest rate.',
       'Major-bank posted rate pages can be product/region dependent or client-rendered. An unavailable quote is not replaced with a made-up figure.',
       'No borrower credit file, borrower identity or new lender commitment is evaluated by this report.',
       'Verify exact renewal terms, insurance portability, security charge type, prepayment features and underwriting with the lender.']:
       story.append(_para('• '+line, 'BodyRR'))
    story.append(Spacer(1,10))
    story.append(_para('Important: Not a lender quote, mortgage approval, legally binding disclosure, or personalized regulated financial advice. All estimates must be reconciled against mortgage terms and written lender statements. No actual bank rates are inferred from sample scenarios.','SmallRR'))
    def footer(canvas,doc):
        canvas.saveState()
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(SMOKE)
        canvas.drawString(52,28,'RENEWAL RADAR  /  EVIDENCE FIRST, DECISIONS SECOND')
        canvas.drawRightString(letter[0]-52,28,f'Page {doc.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return result.getvalue()
