"""Lender-document profiles. These are NOT certifications of penny-exact outputs.

Selection must include product and contract version in later productization:
some lenders have materially different provisions in different mortgage forms.
"""
from .models import LenderProfile, Method

PROFILES = (
    LenderProfile('generic','Unspecified lender',Method.UNKNOWN,
        'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html',
        '2026-10',True,'Avoid suggesting an IRD without documentary evidence.'),
    LenderProfile('rbc','RBC Royal Bank',Method.POSTED_DISCOUNT,
        'https://www.rbcroyalbank.com/mortgages/understanding-mortgage-prepayment-charges.html',
        '2026-10:legacy-illustrative',True,
        'RBC documents both simple example methods and present-value/declining-balance product methods; use contract version.',
        limitations=('Specific RBC contract variants require a separate present-value implementation.',)),
    LenderProfile('rbc_pv','RBC present-value contract',Method.PRESENT_VALUE,
        'https://www.rbcroyalbank.com/mortgages/understanding-mortgage-prepayment-charges.html',
        '2026-10:pv-approx',True,'Declining-balance present value is an approximation; validate against payout quote.'),
    LenderProfile('td','TD Canada Trust',Method.POSTED_DISCOUNT,
        'https://apps.td.com/mortgage-prepayment-calculator/',
        '2026-10:estimated',True,'Discount adjusted comparison rate; version and contract may change handling.'),
    LenderProfile('scotia','Scotiabank',Method.PRESENT_VALUE,
        'https://www.scotiabank.com/content/dam/scotiabank/canada/en/documents/mortgages/What_you_need_to_know_Mortgages_and_Mortgage-Prepayment-Charges_1343814_1202_EN.pdf',
        '2026-10:pv-approx',True,'PV of projected payment streams; payment timing and compounding simplifications disclosed.',
        limitations=('For terms exceeding five years past year five, limits may apply.',)),
    LenderProfile('cibc','CIBC',Method.CIBC,
        'https://www.cibc.com/en/personal-banking/mortgages/calculators/prepayment-calculator.html',
        '2026-10:estimated',True,'Discount added back for the three-month floor on certain contracts; contract controls.'),
    LenderProfile('bmo','BMO',Method.UNKNOWN,
        'https://www.bmo.com/en-ca/main/personal/mortgages/pay-mortgage-faster/',
        '2026-10:unverified',False,'No unverified BMO formula promoted to production.'),
    LenderProfile('nbc','National Bank',Method.UNKNOWN,
        'https://www.nbc.ca/personal/mortgages.html',
        '2026-10:unverified',False,'National Bank-specific IRD formula requires validated product documents.'),
    LenderProfile('first_national','First National',Method.PRESENT_VALUE,
        'https://www.firstnational.ca/residential/mortgage-calculators/prepayment-calculator',
        '2026-10:verified-ratewatch',True,'Present value of the monthly interest differential on the declining balance; reproduced to the cent against First National\'s own calculator in the ratewatch registry.'),
    LenderProfile('mcap','MCAP',Method.UNKNOWN,
        'https://www.mcap.com/residential-mortgages/resources/mortgage-payment-calculator',
        '2026-10:verified-ratewatch',True,'Simple rate differential (contract minus current posted rate for the remaining-term band) x balance x months/12; reproduced to the cent against MCAP\'s own calculator in the ratewatch registry.'),
    LenderProfile('rmg','RMG',Method.UNKNOWN,
        'https://www.rmgmortgages.ca/customers/rate-calculator',
        '2026-10:verified-ratewatch',True,'RMG is a division of MCAP; its own calculator returns MCAP\'s answers at every yearly term (no sub-year reinvestment rates). Reproduced to the cent in the ratewatch registry.'),
    LenderProfile('mcan','MCAN',Method.UNKNOWN,
        'https://mcanfinancial.com/wp-content/uploads/2026/10/MCAN-Home-Mortgage-Current-Interest-Rates-Oct-10-2026.pdf',
        '2026-10:documented-method',False,'Documented method only: greater of IRD or three months\' interest per MCAN Home\'s published lender summaries; no public MCAN calculator exists to calibrate against.'),
)
REGISTRY = {p.code:p for p in PROFILES}
def lender_profiles() -> list[dict]:
    return [dict(vars(p),method=p.method.value) for p in PROFILES]
def profile_for(code: str) -> LenderProfile:
    return REGISTRY.get(code.lower(),REGISTRY['generic'])
