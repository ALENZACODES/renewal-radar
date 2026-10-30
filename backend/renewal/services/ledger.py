"""Exportable loan ledger; figures derive only from the deterministic simulation.

Cash-flow records are estimates; actual lender conventions and posting dates vary.
"""
from __future__ import annotations
import csv
import io
from collections import defaultdict
from ..domain.mortgage_math import simulate
from ..domain.schemas import AnalyzeRequest

COLUMNS = ('offer','payment_number','month','rate','payment','interest','principal','balance','extra','negative_amortization')


def offer_ledgers(request: AnalyzeRequest):
    """All offers simulated on exactly the requested horizon or earlier term end.

    The baseline is constructed from the user's renewal, not scraped data.
    """
    from ..domain.schemas import Offer
    baseline = Offer(name='Your renewal offer',rate=request.mortgage.offered_rate,
        rate_type=request.mortgage.rate_type,term_months=request.mortgage.term_months,
        type='personalized')
    for offer in (baseline, *request.offers):
        horizon=min(offer.term_months,request.horizon_months)
        result=simulate(request.mortgage.balance,offer.rate,
            offer.amortization_months or request.mortgage.amortization_months,horizon,
            request.mortgage.frequency,offer.rate_type,offer.monthly_extra,
            offer.annual_prepayment,offer.variable_path_bps,offer.fixed_payment_variable)
        yield offer,result,horizon


def ledger_csv(request: AnalyzeRequest) -> bytes:
    buf=io.StringIO(newline='')
    writer=csv.DictWriter(buf,fieldnames=COLUMNS,lineterminator='\r\n',extrasaction='ignore')
    writer.writeheader()
    for offer, result, _ in offer_ledgers(request):
        for line in result['schedule']:
            # Prevent formula injection when the file is opened in spreadsheet software.
            name=offer.name
            if name.lstrip().startswith(('=','+','-','@','\t','\r')):
                name="'"+name
            writer.writerow({'offer':name,**line})
    return ('\ufeff'+buf.getvalue()).encode('utf-8')


def annual_summary(request: AnalyzeRequest) -> dict:
    scenarios=[]
    for offer,simulation,horizon in offer_ledgers(request):
        groups=defaultdict(lambda:{'paid':0.0,'interest':0.0,'principal':0.0,'extra':0.0,'count':0})
        for line in simulation['schedule']:
            # Payment # defines exact accounting year (not a rounded fractional month).
            year=(line['payment_number']-1)//simulation['periods_per_year']+1
            item=groups[year]
            for key, source in [('paid','payment'),('interest','interest'),('principal','principal'),('extra','extra')]:
                item[key]+=line[source]
            item['count']+=1
        years=[]
        for year in sorted(groups):
            values=groups[year]
            years.append({'year':year,'payments':values['count'],
                **{key:round(values[key],2) for key in ('paid','interest','principal','extra')}})
        scenarios.append({'offer':offer.name,'rate_type':offer.rate_type,'horizon_months':horizon,
            'shorter_term_than_requested':horizon<request.horizon_months,
            'years':years,'ending_balance':simulation['ending_balance'],
            'total_interest':simulation['total_interest'],
            'total_paid':simulation['total_paid']})
    return {'scenarios':scenarios,'currency':'CAD',
      'note':'Annual groups are payment-years, not calendar years. Each row derives from rounded loan ledger entries; yearly totals may differ slightly from full-precision totals.'}
