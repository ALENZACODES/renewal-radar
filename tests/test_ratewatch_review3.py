"""Regression tests for the third review (5 findings). No network."""
import os
from datetime import date, timedelta

from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import api, backfill, extras as x, live
from renewal.ratewatch.ird import Mortgage, POLICIES, penalty

client = TestClient(app)
TD = POLICIES["TD"]
TERMS = (6, 12, 24, 36, 48, 60, 72, 84, 120)
BODY = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
        "maturity": "2028-10-15", "discount": 2.0}


def test_fetched_rates_are_validated(monkeypatch):
    monkeypatch.setattr(api, "_live_table", lambda lender: ({t: -1.0 for t in TERMS}, "api"))
    r = client.post("/api/ratewatch/penalty", json=BODY)
    assert r.status_code == 502 and "failed validation" in r.text


def test_reverse_rate_finds_narrow_range_near_discount():
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.003, maturity=date(2028, 10, 15))
    day = date(2026, 10, 14)
    q = penalty(m, TD, {t: 2.00303 for t in TERMS}, day)["penalty"]
    res = x.reverse_rate(m, TD, day, q)
    assert any(lo <= 2.00303 <= hi for lo, hi in res["compatible_posted_rate_ranges"]), res


def test_default_payout_before_start_rejected():
    start = (date.today() + timedelta(days=30)).isoformat()
    body = {**BODY, "start": start, "maturity": (date.today() + timedelta(days=1000)).isoformat(),
            "current_posted": {str(t): 5.0 for t in TERMS}}
    r = client.post("/api/ratewatch/penalty", json=body)
    assert r.status_code == 422 and "not started" in r.text


def test_refresh_uses_os_lock_and_never_deletes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "REFRESH_LOCK", tmp_path / "lock")
    monkeypatch.setattr(live, "BOARD", tmp_path / "b.json")
    calls = []
    monkeypatch.setattr(live, "_refresh", lambda lenders=None: calls.append(1) or {"ok": 1})
    holder = open(tmp_path / "lock", "a+b")              # another collector holding the OS lock
    assert live._try_os_lock(holder)
    assert live.refresh().get("busy") and calls == []    # refused while held, however old the file is
    live._os_unlock(holder)
    holder.close()                                       # holder finished (or died: the OS releases it)
    assert live.refresh() == {"ok": 1} and calls == [1]
    assert (tmp_path / "lock").exists()                  # never deleted, so no takeover race


def test_reverse_rate_uses_inferred_discount():
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), {60: 6.89}, None, maturity=date(2028, 10, 15))
    day = date(2026, 10, 14)
    q = penalty(m, TD, {t: 5.291 for t in TERMS}, day)["penalty"]
    res = x.reverse_rate(m, TD, day, q)
    assert any(lo <= 5.291 <= hi for lo, hi in res["compatible_posted_rate_ranges"]), res
    assert res["assumes"]["discount"] == 2.0


def test_reverse_rate_long_term_cap_covers_all_rates():
    m = Mortgage(400_000, 4.89, 120, date(2018, 1, 1), discount=2.0, maturity=date(2028, 1, 1))
    day = date(2026, 10, 14)
    q = penalty(m, TD, {t: 3.0 for t in TERMS}, day)["penalty"]
    assert all(penalty(m, TD, {t: r for t in TERMS}, day)["penalty"] == q for r in (1.0, 3.0, 8.0))
    res = x.reverse_rate(m, TD, day, q)
    assert res["compatible_posted_rate_ranges"] == [(0.0, 15.0)] and not res["unique"]


def test_backfill_retries_when_boc_figure_missing(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(backfill, "PROGRESS", tmp_path / "p.json")
    monkeypatch.setattr(backfill, "COVERAGE", tmp_path / "c.json")
    monkeypatch.setattr(backfill, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(backfill, "SOURCES", {"P021": [("html", "https://example.test/r", "exact")]})
    monkeypatch.setattr(backfill, "months", lambda: ["202501"])
    monkeypatch.setattr(backfill.history, "official", lambda **k: 0)
    monkeypatch.setattr(backfill, "cc_crawls", lambda: [])
    monkeypatch.setattr(backfill, "captures", lambda arc, url, match: {"202501": [("20250108000000", url)]})
    monkeypatch.setattr(backfill, "parse", lambda kind, text: [(60, "fixed_closed", "posted", 6.49)])
    monkeypatch.setattr(backfill, "boc_on", lambda day: None)                 # BoC outage

    class Ok:
        status_code, ok, text = 200, True, "<html/>"
    monkeypatch.setattr(backfill.Archive, "get", lambda self, url, params=None, timeout=120: Ok())
    backfill.run()
    tried = [v for k, v in json.loads(backfill.PROGRESS.read_text()).items() if k.startswith("tried:")]
    assert all("20250108000000" not in t for t in tried)
