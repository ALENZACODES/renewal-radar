"""Broker review reads each lender's posted rates through the live backup chain."""
from datetime import date, timedelta

import pytest

from renewal.broker import book_review as br
from renewal.ratewatch import history, live

TABLE = [(6, 5.54), (12, 5.49), (24, 5.29), (36, 6.05), (48, 5.99), (60, 6.09), (72, 6.29), (84, 6.4), (120, 6.8)]


@pytest.fixture(autouse=True)
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(br, "_board", lambda: {})


def row(tier="primary", label="Live"):
    return {"tier": tier, "tier_label": label, "as_of": "2026-10-15T10:00:00+00:00", "lender_specific": True,
            "rates": {str(t): {"posted": r} for t, r in TABLE}}


def test_fresh_recorded_reading_is_used_without_network(monkeypatch):
    today = date.today()
    history.save("P023", today.isoformat(), [(t, "fixed_closed", "posted", r) for t, r in TABLE], "api")
    calls = []
    monkeypatch.setattr(live, "resolve", lambda *a, **k: calls.append(1))
    t = br.lender_rates({"P023"}, today)
    assert t["P023"][0][60] == 6.09 and calls == []


def test_missing_reading_goes_through_live_chain_once_per_lender(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "resolve", lambda lender, anchor, now=None: calls.append(lender[0]) or row("backup1", "Live (backup source)"))
    t = br.lender_rates({"P021", "P023"}, date.today())
    assert sorted(calls) == ["P021", "P023"]
    assert t["P021"][0][24] == 5.29 and "backup source" in t["P021"][1]


def test_chain_failure_falls_back_to_last_good_reading(monkeypatch):
    old = (date.today() - timedelta(days=5)).isoformat()
    history.save("P021", old, [(t, "fixed_closed", "posted", r) for t, r in TABLE], "html")
    t = br.lender_rates({"P021"}, date.today())                 # conftest makes resolve raise
    assert t["P021"][0][60] == 6.09 and t["P021"][1] == f"recorded {old}"


def test_not_lender_specific_reading_is_not_used(monkeypatch):
    monkeypatch.setattr(live, "resolve", lambda *a, **k: {**row("boc_typical", "Bank of Canada"), "lender_specific": False})
    t = br.lender_rates({"P021"}, date.today())
    assert t["P021"][0] == {}


def test_past_review_never_uses_live_or_later_data(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "resolve", lambda *a, **k: calls.append(1) or row())
    history.save("P021", "2025-03-10", [(60, "fixed_closed", "posted", 6.49)], "html")
    t = br.lender_rates({"P021"}, date(2025, 3, 5))
    assert calls == [] and t["P021"][0] == {}


def test_review_uses_chain_tables_and_reports_source(monkeypatch):
    monkeypatch.setattr(live, "resolve", lambda lender, anchor, now=None: row())
    deal = {"deal_id": "D1", "lender": "RBC", "rate_type": "fixed", "balance": 500000, "contract_rate": 6.5,
            "posted_rate": 8.0, "term_months": 60, "closing_date": "2023-10-16", "maturity_date": "2028-10-16",
            "amort_months": 300}
    r = br.review_book([deal], as_of=date.today(), target_rate=4.4)["results"][0]
    assert r.get("rates_source", "").startswith("Live")
