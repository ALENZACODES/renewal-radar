import asyncio

import httpx
import pytest

from renewal.services import market


def test_newest_official_observation_does_not_depend_on_response_order():
    newest = {'d': '2026-10-13', 'CODE': {'v': '4.5'}}
    oldest = {'d': '2026-10-07', 'CODE': {'v': '4.75'}}
    for observations in ([newest, oldest], [oldest, newest]):
        result = market.latest_official_observation({'observations': observations}, 'CODE', 'Rate')
        assert result['value'] == 4.5
        assert result['observed_at'] == '2026-10-13'


@pytest.mark.parametrize('observations', [
    [{'d': '2026-10-13', 'CODE': {'v': 'NaN'}}],
    [{'d': '2026-10-13', 'CODE': {'v': 'Infinity'}}],
    [{'d': 'not-a-date', 'CODE': {'v': '4.5'}}],
    [{'d': '9999-10-13', 'CODE': {'v': '4.5'}}],
    [{'d': '2026-10-13', 'CODE': '4.5'}],
    [{'d': '2026-10-13', 'OTHER': {'v': '4.5'}}],
    {'not': 'a list'},
])
def test_malformed_observations_are_not_promoted(observations):
    assert market.latest_official_observation({'observations': observations}, 'CODE', 'Rate') is None


def test_combined_request_failure_does_not_hide_valid_individual_series(monkeypatch):
    calls = []
    client_class = httpx.AsyncClient
    def respond(request):
        code = request.url.path.split('/observations/')[1].split('/')[0]
        calls.append(code)
        if ',' in code:
            return httpx.Response(404, json={'message': 'Series unavailable'})
        return httpx.Response(200, json={'observations': [{'d': '2026-10-13', code: {'v': '4.5'}}]})
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(market.httpx, 'AsyncClient', lambda **kwargs: client_class(transport=transport, **kwargs))
    monkeypatch.setattr(market, '_cache', {'at': 0, 'data': None})
    result = asyncio.run(market.fetch_boc(force=True))
    assert result['data_status'] == 'live-observation'
    assert len(result['series']) == 6
    assert len(calls) == 7
    assert result['missing_series'] == []


def test_partial_provider_failure_preserves_other_official_observations(monkeypatch):
    client_class = httpx.AsyncClient
    def respond(request):
        code = request.url.path.split('/observations/')[1].split('/')[0]
        if ',' in code or code == market.SERIES['bond_5y'][0]:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={'observations': [{'d': '2026-10-13', code: {'v': '4.5'}}]})
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(market.httpx, 'AsyncClient', lambda **kwargs: client_class(transport=transport, **kwargs))
    monkeypatch.setattr(market, '_cache', {'at': 0, 'data': None})
    result = asyncio.run(market.fetch_boc(force=True))
    assert len(result['series']) == 5
    assert result['missing_series'] == ['bond_5y']
    assert 'bond_5y' not in result['series']


def test_failed_refresh_labels_prior_observations_as_stale(monkeypatch):
    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={}))
    previous = {'data_status': 'live-observation', 'series': {'prime': {'value': 4.5}}, 'checked_at': 'earlier'}
    monkeypatch.setattr(market.httpx, 'AsyncClient', lambda **kwargs: client_class(transport=transport, **kwargs))
    monkeypatch.setattr(market, '_cache', {'at': 0, 'data': previous})
    result = asyncio.run(market.fetch_boc(force=True))
    assert result['data_status'] == 'cached-stale'
    assert result['from_cache'] is True
    assert result['series']['prime']['value'] == 4.5


def test_bond_series_uses_current_official_valet_identifier():
    assert market.SERIES['bond_5y'][0] == 'BD.CDN.5YR.DQ.YLD'
