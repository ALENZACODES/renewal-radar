"""Optional Tavily discovery, never used as a rate-of-record source.

Can find relevant *official* source URLs for lender claims, but results are
not converted to user-visible quoted rates without checking the bank itself.
"""
import httpx
from urllib.parse import urlparse
from ..config import settings

ALLOWED_DOMAINS={'rbcroyalbank.com','td.com','scotiabank.com','bmo.com','cibc.com','nbc.ca','bankofcanada.ca'}

def official_url(url:str)->bool:
    try:
        parsed=urlparse(url)
        return parsed.scheme=='https' and any(parsed.hostname==host or parsed.hostname.endswith('.'+host) for host in ALLOWED_DOMAINS)
    except (ValueError,AttributeError):return False

async def discover(query:str):
    if not settings.tavily_api_key:
        return {'configured':False,'results':[],'note':'Tavily unavailable without API key.'}
    if len(query)>300:query=query[:300]
    try:
        async with httpx.AsyncClient(timeout=9) as client:
            response=await client.post('https://api.tavily.com/search',json={
              'api_key':settings.tavily_api_key,'query':query,'search_depth':'basic','max_results':8,
              'include_domains':sorted(ALLOWED_DOMAINS)})
            response.raise_for_status();items=response.json().get('results',[])
        data=[{'title':r.get('title','')[:120],'url':r['url'],'snippet':r.get('content','')[:400],
               'status':'discovery-only-unverified'} for r in items if official_url(r.get('url',''))]
        return {'configured':True,'results':data,
                'note':'Search results are not verified mortgage quotes and must be corroborated on official pages.'}
    except (httpx.HTTPError,ValueError,KeyError):
        return {'configured':True,'results':[], 'note':'Tavily request unavailable. No inferred rates returned.'}
