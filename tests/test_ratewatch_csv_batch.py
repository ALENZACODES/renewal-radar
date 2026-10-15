"""Ratewatch CSV batch validation, quarantine, and last-good pointer."""
from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from renewal.ratewatch.batch_store import BatchStore
from renewal.ratewatch.csv_batch import HEADERS, parse_rate_csv, sanity_vs_last_good


def _csv(rows: list[str], *, bom: bool = True) -> bytes:
    body = ','.join(HEADERS) + '\n' + '\n'.join(rows) + '\n'
    data = body.encode('utf-8')
    return (b'\xef\xbb\xbf' + data) if bom else data


def _row(lender='TD', term=60, rate='5.25', day='2026-10-01', rtype='posted') -> str:
    return f'{day},{lender},{term},{rate},{rtype}'


@pytest.fixture
def store(tmp_path):
    return BatchStore(tmp_path / 'csv_batches')


def test_parse_rejects_wrong_headers():
    data = b'date,bank,term,rate\n2026-10-01,TD,60,5.25\n'
    parsed = parse_rate_csv(data)
    assert not parsed.ok
    assert any('exact headers' in e for e in parsed.errors)


def test_parse_rejects_outlier_rate_and_bad_term():
    data = _csv([_row(rate='25.01'), _row(lender='RBC', term=99, rate='4.50')])
    parsed = parse_rate_csv(data)
    assert not parsed.ok
    assert any('0..25' in e for e in parsed.errors)
    assert any('allowlist' in e for e in parsed.errors)


def test_parse_rejects_duplicates_and_accepts_utf8_sig():
    data = _csv([_row(), _row()])
    parsed = parse_rate_csv(data)
    assert not parsed.ok
    assert any('duplicate' in e for e in parsed.errors)
    good = _csv([_row(), _row(lender='RBC', rate='5.10')])
    ok = parse_rate_csv(good)
    assert ok.ok and len(ok.rows) == 2
    assert ok.rows[0].rate_pct == __import__('decimal').Decimal('5.25')


def test_corrupt_csv_quarantined_preserves_last_good(store):
    good = _csv([
        _row('TD', 60, '5.25'),
        _row('RBC', 60, '5.29'),
        _row('BMO', 60, '5.34'),
        _row('CIBC', 60, '5.39'),
        _row('Scotia', 60, '5.44'),
    ])
    first = store.import_csv(good, source='seed')
    assert first['status'] == 'active'
    active_sha = first['sha256']
    last = store.last_good()
    assert last and last['sha256'] == active_sha

    corrupt = b'\xff\xfe not utf8'
    result = store.import_csv(corrupt, source='bad')
    assert result['status'] == 'quarantined'
    assert store.pointer()['sha256'] == active_sha
    assert store.last_good()['sha256'] == active_sha
    assert store.active_rows()  # still readable
    assert any(e['sha256'] == result['sha256'] for e in store.list_quarantine())


def test_outlier_rate_quarantines_whole_batch(store):
    seed = _csv([_row('TD', 60, '5.25'), _row('RBC', 60, '5.29'), _row('BMO', 60, '5.34'),
                 _row('CIBC', 60, '5.39'), _row('Scotia', 60, '5.44')])
    store.import_csv(seed)
    bad = _csv([_row('TD', 60, '5.25'), _row('RBC', 60, '99.00')])  # 99 fails schema
    result = store.import_csv(bad)
    assert result['status'] == 'quarantined'
    assert any('0..25' in r or 'rate_pct' in r for r in result['reasons'])


def test_sanity_rate_jump_and_missing_lender(store):
    seed_rows = [
        _row('TD', 60, '5.25'),
        _row('RBC', 60, '5.29'),
        _row('BMO', 60, '5.34'),
        _row('CIBC', 60, '5.39'),
        _row('Scotia', 60, '5.44'),
    ]
    store.import_csv(_csv(seed_rows))
    # Jump + missing Scotia
    jumped = _csv([
        _row('TD', 60, '8.50'),  # +3.25 pp
        _row('RBC', 60, '5.29'),
        _row('BMO', 60, '5.34'),
        _row('CIBC', 60, '5.39'),
    ])
    result = store.import_csv(jumped)
    assert result['status'] == 'quarantined'
    joined = ' '.join(result['reasons'])
    assert 'rate jump' in joined
    assert 'missing lender' in joined
    assert store.last_good()['sha256'] == store.pointer()['sha256']


def test_row_count_swing_quarantine(store):
    seed = _csv([_row(f'L{i}', 60, '5.00') for i in range(10)])
    store.import_csv(seed)
    tiny = _csv([_row('L0', 60, '5.00'), _row('L1', 60, '5.00')])
    result = store.import_csv(tiny)
    assert result['status'] == 'quarantined'
    assert any('row count swing' in r for r in result['reasons'])


def test_same_sha_noop(store):
    data = _csv([_row(), _row(lender='RBC', rate='5.10')])
    a = store.import_csv(data)
    b = store.import_csv(data)
    assert a['status'] == 'active' and b['status'] == 'noop'
    assert a['sha256'] == b['sha256']


def test_http_ingest_and_active_reader(tmp_path, monkeypatch):
    monkeypatch.setenv('RR_RATE_INGEST_KEY', 'very-long-development-ingest-key-2026')
    monkeypatch.setenv('RATEWATCH_DATA', str(tmp_path))
    # Re-bind default store path via env before import of app routes using default_store
    from renewal.ratewatch import batch_store as bs
    bs.default_store = bs.BatchStore(tmp_path / 'csv_batches')

    from renewal.main import app
    client = TestClient(app)
    headers = {'X-Rate-Ingest-Key': 'very-long-development-ingest-key-2026'}
    good = _csv([
        _row('TD', 60, '5.25'),
        _row('RBC', 60, '5.29'),
        _row('BMO', 60, '5.34'),
        _row('CIBC', 60, '5.39'),
        _row('Scotia', 60, '5.44'),
    ])
    r = client.post(
        '/api/ratewatch/batches/csv',
        headers=headers,
        files={'file': ('rates.csv', good, 'text/csv')},
    )
    assert r.status_code == 201, r.text
    assert r.json()['status'] == 'active'
    active = client.get('/api/ratewatch/batches/active')
    assert active.status_code == 200
    assert len(active.json()['rows']) == 5

    bad = client.post(
        '/api/ratewatch/batches/csv',
        headers=headers,
        files={'file': ('bad.csv', _csv([_row(rate='30')]), 'text/csv')},
    )
    assert bad.status_code == 422
    assert bad.json()['status'] == 'quarantined'
    # last-good still present
    lg = client.get('/api/ratewatch/batches/last-good')
    assert lg.json()['last_good']['sha256'] == r.json()['sha256']
    # without key
    assert client.post(
        '/api/ratewatch/batches/csv',
        files={'file': ('rates.csv', good, 'text/csv')},
    ).status_code == 403
