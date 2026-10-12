"""Structured scripts, not a falsely certified lender offer."""
from ..domain.schemas import NegotiationRequest
from ..domain.mortgage_math import scheduled_payment


def negotiation_packet(req:NegotiationRequest):
    m=req.mortgage
    existing=scheduled_payment(m.balance,m.offered_rate,m.amortization_months,m.frequency,m.rate_type)
    competing=scheduled_payment(m.balance,req.competing_rate,m.amortization_months,m.frequency,m.rate_type)
    diff=existing-competing
    proof='I have a written competing offer' if req.competitor_offer_verified else 'I am evaluating an illustrative alternative and will confirm actual quotes'
    opening=(f"My mortgage is approaching renewal and I have received a {m.offered_rate:.2f}% offer for a {m.term_months//12 if m.term_months%12==0 else m.term_months}-{'year' if m.term_months%12==0 else 'month'} term. "
      f"{proof} around {req.competing_rate:.2f}%. Could your retention team review the renewal rate and conditions before I make a decision?")
    if req.goals=='flexibility':request='I would also like the written prepayment privileges, portability rules, and fixed-rate penalty methodology.'
    elif req.goals=='lower_payment':request='Please provide your strongest rate and an updated principal-and-interest payment schedule.'
    else:request='Please provide your most competitive rate and the total interest estimate over the proposed term.'
    facts=(f'At my estimated balance of ${m.balance:,.0f} and {m.amortization_months//12} years remaining, the illustrative principal-and-interest difference is ${diff:,.2f} per {m.frequency} payment. This assumes the same amortization and no fees or prepayments.')
    script=[
      'Hello, I am reviewing my upcoming mortgage renewal and want to speak with your mortgage retention specialist.',
      opening, facts, request,
      'Could you confirm whether that rate is a firm renewal offer and whether any additional fees apply?',
      'Please email the revised proposal with the rate, term, amortization, payment, prepayment privileges, charge type, and expiry date.',
      'I will compare the written proposal with alternatives and follow up before maturity.'
    ]
    email=(f'Subject: Request to review mortgage renewal offer\n\nHello,\n\n{opening}\n\n{request}\n\n'
       'Please send your best written offer and confirm all applicable conditions, fees and prepayment privileges. '
       'I am reviewing my options ahead of the maturity date and would appreciate a response before that date.\n\nThank you.')
    questions=['Is this a posted, special, or individually approved renewal rate?',
      'Can the rate be held until maturity, and when does the offer expire?',
      'What is the cost of breaking this contract before its next maturity?',
      'Can this mortgage transfer to another lender without collateral-charge discharge or HELOC restructuring?',
      'What are the annual lump-sum and payment-increase limits?',
      'Will you waive discharge, transfer, appraisal or legal fees?',
      'What would the payment and principal balance be at the end of the new term?']
    return {'call_script':script,'email':email,'questions':questions,
            'modelled_payment_difference':round(diff,2),'offer_verified':req.competitor_offer_verified,
            'notice':'Illustrative alternative is not a lender quote unless a verifiable written offer is supplied.'}
