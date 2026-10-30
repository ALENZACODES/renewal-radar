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
    LenderProfile('first_national','First National',Method.UNKNOWN,
        'https://www.firstnational.ca/residential',
        '2026-10:unverified',False,'Monoline rules depend on product and registered mortgage terms.'),
    LenderProfile('mcap','MCAP',Method.UNKNOWN,
        'https://www.mcap.com/residential-mortgages',
        '2026-10:unverified',False,'Do not generalize all monoline contracts.'),
)
REGISTRY = {p.code:p for p in PROFILES}
def lender_profiles() -> list[dict]:
    return [dict(vars(p),method=p.method.value) for p in PROFILES]
def profile_for(code: str) -> LenderProfile:
    return REGISTRY.get(code.lower(),REGISTRY['generic'])
