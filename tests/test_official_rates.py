"""Deterministic tests: zero traffic to public financial institutions."""
from datetime import datetime,timezone
import json
import httpx
import pytest

from renewal.intelligence.rate_history import RateArchive
from renewal.pipelines.official_rates import (
    OfficialSource,OfficialRateCollector,public_addresses,
    evidence_from_page,load_source_manifest,collect_approved_sources)

URL='https://mortgages.example.org/rates'
HTML=b'''<html><head><title>Mortgage rates</title></head><body><table>
<thead><tr><th>Product</th><th>Posted fixed rate</th></tr></thead>
<tr><td>5-year fixed</td><td>5.39%</td></tr>
</table></body></html>'''


def source(**overrides):
    opts={'lender':'Example Financial','url':URL,'allowed_host':'mortgages.example.org',
          'permission_confirmed':True}
    opts.update(overrides)
    return OfficialSource(**opts)


def client_transport(content=HTML,status=200,headers=None):
    def respond(request):
        return httpx.Response(status,headers=headers or {'content-type':'text/html'},content=content)
    return httpx.MockTransport(respond)


@pytest.mark.parametrize('wrong',[
    {'url':'http://mortgages.example.org/rates'},
    {'url':'https://other.example.org/rates'},
    {'url':'https://user:pass@mortgages.example.org/rates'},
    {'permission_confirmed':False},
    {'term_months':36},
])
def test_policy_rejects_unapproved_or_mismatched_sources(wrong):
    with pytest.raises(ValueError):
        source(**wrong).check()


def test_global_address_policy():
    assert public_addresses('host',resolver=lambda _:['8.8.8.8'])
    for address in ('127.0.0.1','10.1.1.1','169.254.169.254','192.168.1.1','::1'):
        assert not public_addresses('host',resolver=lambda _,a=address:[a])
    assert not public_addresses('host',resolver=lambda _:[])
    assert not public_addresses('host',resolver=lambda _:['8.8.8.8','127.0.0.1'])


def test_evidence_requires_unique_rate():
    parsed=evidence_from_page(HTML)
    assert parsed['status']=='verified'
    assert parsed['rate']=='5.39'
    assert evidence_from_page(b'<html><body>5.39%</body></html>')['status']=='unverified'
    assert evidence_from_page(b'\xff')['status']=='rejected'
    assert evidence_from_page(b'x'*1500001)['status']=='rejected'


@pytest.mark.asyncio
async def test_capture_stores_provenance_and_is_idempotent(tmp_path):
    db=RateArchive(tmp_path/'rates.sqlite')
    collector=OfficialRateCollector(db,transport=client_transport())
    moment=datetime(2026,10,12,tzinfo=timezone.utc)
    first=await collector.collect(source(),captured_at=moment)
    second=await collector.collect(source(),captured_at=moment)
    assert first.status=='stored'
    assert first.observation_id==second.observation_id
    assert len(db.history('Example Financial'))==1
    record=db.history('Example Financial')[0]
    assert record['annual_rate']=='5.39'
    assert record['source_sha256']==first.content_sha256
    assert record['provenance']=='official_auto_capture'
    assert record['effective_at']==moment.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers,body',[
    (302,{'content-type':'text/html','location':'http://localhost/'},b''),
    (200,{'content-type':'application/json'},b'{}'),
    (200,{'content-type':'text/html'},b'no rate here'),
    (200,{'content-type':'text/html'},b'x'*1500001),
    (503,{'content-type':'text/html'},b'error'),
], ids=['redirect', 'json', 'ambiguous_html', 'oversize_html', 'http_error'])
async def test_bad_sources_never_pollute_archive(tmp_path,status,headers,body):
    archive=RateArchive(tmp_path/'rates.sqlite')
    result=await OfficialRateCollector(archive,transport=client_transport(body,status,headers)).collect(source())
    assert result.status!='stored'
    assert archive.history('Example Financial')==[]


@pytest.mark.asyncio
async def test_missing_permission_never_fetches(tmp_path):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,headers={'content-type':'text/html'},content=HTML)
    archive=RateArchive(tmp_path/'rates.sqlite')
    collector=OfficialRateCollector(archive,transport=httpx.MockTransport(respond))
    result=await collector.collect(source(permission_confirmed=False))
    assert result.status=='rejected' and not requests


def test_manifest_requires_operator_approval(tmp_path):
    path=tmp_path/'config.json'
    path.write_text(json.dumps([{'lender':'Example Financial','url':URL,
       'allowed_host':'mortgages.example.org','permission_confirmed':True}]))
    assert len(load_source_manifest(path))==1
    path.write_text(json.dumps([{'lender':'Example Financial','url':URL,
       'allowed_host':'mortgages.example.org','permission_confirmed':False}]))
    with pytest.raises(ValueError):
        load_source_manifest(path)


@pytest.mark.asyncio
async def test_sequential_batch_tracks_per_source_failure(tmp_path):
    archive=RateArchive(tmp_path/'rates.sqlite')
    collector=OfficialRateCollector(archive,transport=client_transport())
    results=await collect_approved_sources(archive,[source(),source(permission_confirmed=False)],collector=collector)
    assert [r['status'] for r in results]==['stored','rejected']
