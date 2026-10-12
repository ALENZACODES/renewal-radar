"""Conservative live official bank-site adapter.

We extract ONLY a 5-year fixed *posted* rate when the bank's own server-side
HTML pairs that exact product label with an unambiguous percentage.
Official sites often render rates client-side, or show rates requiring regional
and insurance parameters. In those cases, return status 'needs-verification'
without a numeric quote. No stale or invented values enter comparisons.
"""
from __future__ import annotations
import asyncio,re
from datetime import datetime,timezone
from bs4 import BeautifulSoup
import httpx
from ..services.market import BANK_SOURCES

RATE_RE=re.compile(r'(?<!\d)(\d{1,2}\.\d{1,3})\s*%')
TERM_RE=re.compile(r'\b(?:5\s*[- ]?year|five\s*[- ]year|5\s*yr)\b',re.I)
POSTED_RE=re.compile(r'\bposted\b',re.I)
FIXED_RE=re.compile(r'\bfixed\b',re.I)


def parse_official_posted_html(html:str)->dict:
    """Fail closed if a public HTML table is ambiguous."""
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','noscript','template']):tag.decompose()
    candidates=[]
    for row in soup.select('tr'):
        txt=' '.join(row.get_text(' ',strip=True).split())
        table=row.find_parent('table')
        context=' '.join(table.select_one('thead').get_text(' ',strip=True).split()) if table and table.select_one('thead') else ''
        combined=txt+' '+context
        if not (TERM_RE.search(txt) and FIXED_RE.search(combined) and POSTED_RE.search(combined)):
            continue
        vals=[float(m.group(1)) for m in RATE_RE.finditer(txt)]
        # Only promote unambiguous row with a single rate (no other promotional APR).
        if len(vals)==1 and 0.1<=vals[0]<=20:
            candidates.append((vals[0],txt[:300]))
    if len(candidates)==1:
        return {'value':candidates[0][0],'label':'5-year fixed posted',
                'evidence':candidates[0][1], 'confidence':'labelled-row'}
    return {'value':None,'status':'needs-verification',
            'reason': 'No uniquely labelled five-year fixed posted mortgage rate found in server-rendered official table.'}


async def _one(client:httpx.AsyncClient,name:str,url:str)->dict:
    stamp=datetime.now(timezone.utc).isoformat()
    base={'lender':name,'source_url':url,'rate_type':'5-year fixed posted',
          'retrieved_at':stamp,'verified':False,'quote':None,'status':'needs-verification',
          'message':'Official source could not be promoted to a verified product-specific posted rate.'}
    try:
        response=await client.get(url)
        response.raise_for_status()
        result=parse_official_posted_html(response.text)
        if result.get('value') is not None:
            base.update(quote=result['value'],verified=True,status='page-verified',
                        evidence=result['evidence'],
                        message='Unique five-year posted fixed rate extracted from an official HTML table; product eligibility must still be verified.')
    except (httpx.HTTPError,ValueError):
        base['message']='Official bank webpage unavailable or rejected automated retrieval. Use the direct official link.'
    return base


async def fetch_bank_posted_rates()->list[dict]:
    timeout=httpx.Timeout(5.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True,headers={
      'User-Agent':'Mozilla/5.0 (compatible; RenewalRadar/2.0; official bank-rate comparison)'}) as client:
        return await asyncio.gather(*[_one(client,name,url) for name,url in BANK_SOURCES])
