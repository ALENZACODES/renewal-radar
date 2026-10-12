"""Dated Canadian mortgage renewal policy pathways: not an approval engine."""
from __future__ import annotations
from .schemas import Mortgage

OSFI_MQR = 'https://www.osfi-bsif.gc.ca/en/supervision/financial-institutions/banks/minimum-qualifying-rate-uninsured-mortgages'
OSFI_SWITCH = 'https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/osfi-exempts-uninsured-mortgage-straight-switches-prescribed-mqr-implements-portfolio-lti-limits'
INSURED_SWITCH = 'https://www.canada.ca/en/department-finance/news/2024/12/boldest-mortgage-reforms-in-decades-come-into-force-today.html'
PORTFOLIO = 'https://www.canada.ca/en/department-finance/news/2024/12/straight-switches-and-portfolio-insurance.html'
RENEWAL = 'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/renew-mortgage.html'
PENALTY = 'https://www.canada.ca/en/financial-consumer-agency/services/mortgages/reduce-prepayment-penalties.html'


def mqr(contract_rate: float)-> float:
    return round(max(5.25,contract_rate+2),2)


def switch_decision(m:Mortgage, new_contract_rate:float|None=None) ->dict:
    rate = m.offered_rate if new_contract_rate is None else new_contract_rate
    reasons = []; checks=[]; needs=[]
    change= m.cash_out > 0 or m.amortization_increase or m.fees_financed > 3000
    if m.cash_out: reasons.append('Equity withdrawal is not a straight switch.')
    if m.amortization_increase: reasons.append('Remaining contractual amortization increases.')
    if m.fees_financed>3000: reasons.append('Financed related costs exceed the $3,000 permitted allowance under the cited OSFI switch pathway.')
    if change:
        return {'status':'new-underwriting','headline':'Treat as a refinance or new credit assessment',
         'prescribed_mqr_applies':'typically','qualifying_rate':mqr(rate),
         'reasons':reasons,'to_verify':['Lender underwriting, insurer and provincial rules'],
         'sources':[OSFI_MQR,OSFI_SWITCH],
         'disclaimer':'An illustrative qualifying rate is not credit approval or a payment forecast.'}
    if m.insurance_status=='insured':
        if m.combined_loan_plan:
            needs.append('Combined loan or collateral/HELOC structure must be assessed by the lender.')
        reasons=['Federal mortgage charter provides an insured mortgage renewal switching exemption from a new prescribed stress test, subject to conditions.']
        return {'status':'review' if needs else 'potentially-exempt',
          'headline':'Potential insured renewal switch exemption' if not needs else 'Verify insurance portability and loan structure',
          'prescribed_mqr_applies':'potentially-no','qualifying_rate':None,
          'reasons':reasons,'to_verify':needs+['Confirm active insurance and certificate portability','Confirm new lender underwriting and product rules'],
          'sources':[INSURED_SWITCH,RENEWAL], 'disclaimer':'Exemption from repeating the prescribed stress test does not imply automatic approval.'}
    if m.insurance_status=='unknown':
        return {'status':'review','headline':'Confirm mortgage default-insurance status first',
         'prescribed_mqr_applies':'unknown','qualifying_rate':None,
         'reasons':['Different renewal switching pathways apply to insured versus uninsured mortgages.'],
         'to_verify':['Obtain evidence of insured or uninsured status'], 'sources':[INSURED_SWITCH,OSFI_SWITCH],
         'disclaimer':'No exemption determination without confirming insurance and loan type.'}
    if m.standalone is False or m.combined_loan_plan is True:
        reasons.append('Combined or readvanceable loan plans are outside the stand-alone uninsured OSFI exemption.')
        return {'status':'review','headline':'Loan structure may prevent a straight-switch exemption',
          'prescribed_mqr_applies':'unknown','qualifying_rate':mqr(rate),
          'reasons':reasons,'to_verify':['Ask if mortgage is stand-alone and not readvanceable','Confirm whether refinancing underwriting applies'],
          'sources':[OSFI_SWITCH,OSFI_MQR], 'disclaimer':'Rules depend on final transfer structure and lender assessment.'}
    if m.standalone is None or m.combined_loan_plan is None:
        needs.append('Confirm mortgage is a stand-alone non-readvanceable loan.')
    if m.existing_lender_federally_regulated is False or m.new_lender_federally_regulated is False:
        return {'status':'review','headline':'OSFI FRFI-to-FRFI pathway not established',
          'prescribed_mqr_applies':'unknown','qualifying_rate':None,
          'reasons':['The OSFI exemption is scoped to transfers from one federally regulated financial institution to another.'],
          'to_verify':['Assess portfolio insurance alternative, if eligible','Confirm applicable lender and insurer rules'],
          'sources':[OSFI_SWITCH,PORTFOLIO], 'disclaimer':'Provincially regulated lender pathways require separate review.'}
    if m.existing_lender_federally_regulated is None or m.new_lender_federally_regulated is None:
        needs.append('Confirm both existing and receiving lenders are federally regulated.')
    if needs:
        return {'status':'review','headline':'Straight-switch exemption requires verification',
          'prescribed_mqr_applies':'unknown','qualifying_rate':None,
          'reasons':['No cash-out, no amortization increase and related financed fees within OSFI allowance appear satisfied.'],
          'to_verify':needs, 'sources':[OSFI_SWITCH],
          'disclaimer':'A lender may still apply its own underwriting criteria.'}
    return {'status':'potentially-exempt','headline':'Potentially eligible for OSFI straight-switch relief',
          'prescribed_mqr_applies':'not-prescribed','qualifying_rate':None,
          'reasons':['Existing stand-alone uninsured mortgage transferred between federally regulated lenders at maturity.',
            'No additional amortization or equity withdrawal; financed related costs no more than $3,000.'],
          'to_verify':['Verify mortgage documentation and lender identity','New lender must approve and may set its own qualifying criteria'],
          'sources':[OSFI_SWITCH,OSFI_MQR],'disclaimer':'OSFI does not prescribe MQR for qualifying straight switches; lenders independently assess creditworthiness.'}


def penalty_estimate(balance:float,current_rate:float, rate_type:str, remaining_term_months:int,
         comparison_rate:float|None=None, original_posted_rate:float|None=None,
         original_discount:float|None=None, contract_method:str='unknown',is_open:bool=False)->dict:
    if remaining_term_months==0 or is_open:
        return {'three_month_interest':0,'ird_estimate':0,'estimated_penalty':0,'penalty_basis':'None at maturity / open mortgage model',
          'exact_quote_required':is_open,'source':PENALTY,
          'disclaimer':'Some open mortgages have administrative charges; check the contract.'}
    three=balance*(current_rate/100)*(3/12)
    ird=None; note='IRD not estimated without a documented comparison rate and contract methodology.'
    if comparison_rate is not None:
        applied=comparison_rate
        base=current_rate
        if contract_method=='posted-discount':
            if original_posted_rate is None or original_discount is None:
                note='Posted-minus-discount IRD needs original posted rate and discount.'
            else:
                base=original_posted_rate
                applied=max(0,comparison_rate-original_discount)
                ird=max(0,balance*(base-applied)/100*(remaining_term_months/12))
                note='Approximate original-posted-rate-minus-discount convention; not a lender payout quote.'
        elif contract_method=='simple':
            ird=max(0,balance*(current_rate-applied)/100*(remaining_term_months/12))
            note='Simplified interest differential; actual lender IRD may differ materially.'
    if rate_type=='variable':
        estimate=three
        basis='3-month-interest proxy for variable-rate closed mortgage'
    elif ird is not None:
        estimate=max(three,ird)
        basis='Greater of 3-month interest and illustrative IRD'
    else:
        estimate=None
        basis='Three-month floor only; exact higher-of charge unknown'
    return {'three_month_interest':round(three,2),'ird_estimate':round(ird,2) if ird is not None else None,
      'estimated_penalty':round(estimate,2) if estimate is not None else None,
      'penalty_basis':basis,'exact_quote_required':True,'source':PENALTY,'disclaimer':note+' Request a dated written payout statement from the lender.'}
