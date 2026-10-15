from datetime import datetime, timezone
import httpx
import pytest
from renewal.intelligence.rate_history import RateArchive
from renewal.intelligence.collector import CollectionJournal, RateCollector, OfficialSource

SOURCE = OfficialSource('Demo Bank', 'https://rates.example.org/mortgage')
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
HTML = b'<table><thead><tr><th>Posted fixed mortgage rates</th></tr></thead><tbody><tr><td>5-year fixed</td><td>5.39%</td></tr></tbody></table>'


def services(tmp_path):
    archive = RateArchive(tmp_path / 'rates.db')
    journal = CollectionJournal(tmp_path / 'journal.db')
    return archive, journal, RateCollector(archive, journal, [SOURCE])


@pytest.mark.asyncio
async def test_verified_ingestion_and_idempotency(tmp_path):
    archive, journal, collector = services(tmp_path)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=HTML, headers={'content-type': 'text/html'}))
    async with httpx.AsyncClient(transport=transport) as client:
        a = await collector.collect_one(SOURCE, client, now=NOW)
        b = await collector.collect_one(SOURCE, client, now=NOW)
    assert a['status'] == 'verified_public_posted'
    assert a['observation_id'] == b['observation_id']
    assert len(archive.history('Demo Bank')) == 1
    assert len(journal.recent()) == 1
    assert archive.history('Demo Bank')[0]['annual_rate'] == '5.39'


@pytest.mark.asyncio
@pytest.mark.parametrize('body,content_type,status', [
    (b'<h1>Promotional rate 4.2%</h1>', 'text/html', 'ambiguous_quarantined'),
    (b'not html', 'application/pdf', 'content_type_quarantined'),
    (b'x' * 2_000_001, 'text/html', 'oversize_quarantined'),
], ids=['ambiguous_html', 'wrong_content_type', 'oversize_html'])
async def test_fail_closed(tmp_path, body, content_type, status):
    archive, journal, collector = services(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers={'content-type': content_type}))
    async with httpx.AsyncClient(transport=transport) as client:
        event = await collector.collect_one(SOURCE, client, now=NOW)
    assert event['status'] == status
    assert archive.history('Demo Bank') == []
    assert journal.recent()[0]['status'] == status


@pytest.mark.asyncio
async def test_redirects_quarantined(tmp_path):
    archive, _, collector = services(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={'Location': 'http://localhost/admin'}))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await collector.collect_one(SOURCE, client)
    assert result['status'] == 'redirect_quarantined'
    assert not archive.history('Demo Bank')


@pytest.mark.asyncio
async def test_batch_is_explicitly_bounded(tmp_path):
    archive, _, collector = services(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=HTML, headers={'content-type': 'text/html'}))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await collector.run(client)
        assert result['attempted'] == 1 and result['verified'] == 1
        with pytest.raises(ValueError):
            await collector.run(client, parallel=0)


@pytest.mark.asyncio
async def test_unknown_source_denied(tmp_path):
    _, _, collector = services(tmp_path)
    outsider = OfficialSource('Other', 'https://other.example.net')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match='registered'):
            await collector.collect_one(outsider, client)


def test_source_host_validation(tmp_path):
    with pytest.raises(ValueError):
        RateCollector(RateArchive(tmp_path / 'a.db'), CollectionJournal(tmp_path / 'b.db'),
                      [OfficialSource('Local', 'http://localhost/private')])


def test_rate_history_not_backfilled(tmp_path):
    archive, _, _ = services(tmp_path)
    result = archive.reconstruct_discount('Demo Bank', NOW.isoformat(), '4.19', 60)
    assert result['status'] == 'insufficient_evidence'
