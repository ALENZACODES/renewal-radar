"""No invented rates: Bank of Canada live official JSON, cautious bank source catalogue.

Bank pages are linked with verification state. We do NOT mark an HTML fragment as a
current quote unless its source, date, term and product type can be established.
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime,timezone
import httpx

SERIES={
 'policy_rate':('V39079','Bank of Canada overnight target'),
 'posted_1y':('V80691333','BoC major-bank posted 1-year mortgage benchmark'),
 'posted_3y':('V80691334','BoC major-bank posted 3-year mortgage benchmark'),
 'posted_5y':('V80691335','BoC major-bank posted 5-year mortgage benchmark'),
 'prime':('V80691311','BoC typical bank prime rate'),
 'bond_5y':('V39053','Government of Canada 5-year benchmark bond yield')}
BANK_SOURCES=[
 ('RBC','https://www.rbcroyalbank.com/mortgages/mortgage-rates.html'),
 ('TD','https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates'),
 ('Scotiabank','https://www.scotiabank.com/ca/en/personal/rates-prices/mortgages-rates.html'),
 ('BMO','https://www.bmo.com/en-ca/main/personal/mortgages/mortgage-rates/'),
 ('CIBC','https://www.cibc.com/en/interest-rates/mortgage-rates.html'),
 ('National Bank','https://www.nbc.ca/personal/mortgages/rates.html')]
_cache={'at':0,'data':None}


def bank_catalog():
    return [{'lender':name,'source_url':url,'status':'official-source-link',
             'quote':None,'verified':False,
             'message':'Rate not imported as a verified quote. Check the bank page for its current product, province, special/posted distinction and terms.'}
            for name,url in BANK_SOURCES]


async def fetch_boc(force:bool=False):
    if not force and _cache['data'] and time.time()-_cache['at'] < 3600:
        return {**_cache['data'],'from_cache':True}
    ids=','.join(item[0] for item in SERIES.values())
    url=f'https://www.bankofcanada.ca/valet/observations/{ids}/json?recent=12'
    checked=datetime.now(timezone.utc).isoformat()
    output={'provider':'Bank of Canada / Valet','source_url':url,'checked_at':checked,
            'data_status':'unavailable','series':{},'bank_sources':bank_catalog(),'from_cache':False}
    try:
        async with httpx.AsyncClient(timeout=8,follow_redirects=False,headers={'User-Agent':'RenewalRadar/2.0 (financial educational research)'}) as client:
            response=await client.get(url)
            response.raise_for_status()
            content=response.json()
        observations=content.get('observations',[])
        for name,(code,title) in SERIES.items():
            for observation in reversed(observations):
                if code not in observation:continue
                raw=observation[code].get('v')
                try:rate=float(raw)
                except (TypeError,ValueError):continue
                output['series'][name]={'value':rate,'label':title,'observed_at':observation['d'],
                  'code':code,'source_url':f'https://www.bankofcanada.ca/valet/observations/{code}/json?recent=5',
                  'type':'official-historical-observation'}
                break
        output['data_status']='live-observation' if output['series'] else 'unavailable'
        if output['series']:
            _cache.update(at=time.time(),data=output)
    except (httpx.HTTPError,ValueError,KeyError) as exc:
        output['warning']='Official data could not be retrieved. No rate was substituted.'
        if _cache['data']:
            old=_cache['data']
            return {**old,'data_status':'cached-stale','checked_at':checked,
                  'from_cache':True,'warning':'BoC unavailable; cached observations are not live.'}
    return output
