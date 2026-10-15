"""Regression tests for the second review (14 findings). No network."""
import csv
import json
import threading
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import accuracy, backfill, backtest, extras as x, history, live
from renewal.ratewatch.ird import Mortgage, POLICIES, penalty

client = TestClient(app)
TD = POLICIES["TD"]
TABLE = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}
DAY = date(2026, 10, 14)
BODY = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
        "maturity": "2028-10-15", "discount": 2.0, "payout": "2026-10-14",
        "current_posted": {str(k): v for k, v in TABLE.items()}}


def mortgage(**kw):
    base = dict(balance=400_000, contract_rate=4.89, term_months=60, start=date(2023, 10, 15), discount=2.0,
                maturity=date(2028, 10, 15))
    base.update(kw)
    return Mortgage(**base)


# 1: no negative interest after repayment
def test_interest_stops_after_repayment_and_never_goes_negative():
    path = x._interest_path(10_000, 5.0, 12, 60)            # 1-year amortization, 5-year horizon
    assert min(path) >= 0 and sum(path[13:]) == 0
    m = mortgage(balance=50_000, amort_months=24)
    ns = x.net_switch_benefit(m, TD, TABLE, DAY, 3.0, 0, horizon_months=24)
    assert ns["interest_saved"] >= 0 and ns["interest_saved"] < 50_000 * 0.05 * 2


# 2: unsupported products are rejected, not answered as fixed
@pytest.mark.parametrize("extra", [{"rate_type": "variable"}, {"is_open": True}, {"surprise_field": 1}])
def test_unsupported_products_and_unknown_fields_rejected(extra):
    assert client.post("/api/ratewatch/penalty", json={**BODY, **extra}).status_code == 422


# 3: a past payout never uses today's live rates
def test_past_payout_without_table_uses_history_or_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "r.db")
    from renewal.ratewatch import api
    monkeypatch.setattr(api, "_live_table", lambda lender: (_ for _ in ()).throw(AssertionError("live rates used")))
    body = {k: v for k, v in BODY.items() if k != "current_posted"}
    assert client.post("/api/ratewatch/penalty", json={**body, "payout": "2025-03-05"}).status_code == 422
    history.save("P023", "2025-03-03", [(t, "fixed_closed", "posted", r) for t, r in TABLE.items()], "html")
    r = client.post("/api/ratewatch/penalty", json={**body, "payout": "2025-03-05"})
    assert r.status_code == 200 and r.json()["rates_source"] == "history (2025-03-03)"


# 4: client text cannot inject PDF markup
def test_letter_escapes_client_markup():
    import pymupdf
    evil = '<img src="http://evil.test/x.png" width="10" height="10"/><font size="40">Big</font> Smith'
    r = client.post("/api/ratewatch/letter", json={**BODY, "client_name": evil})
    assert r.status_code == 200
    text = pymupdf.open(stream=r.content, filetype="pdf")[0].get_text()
    assert "<img" in text and "<font" in text                 # shown literally, not interpreted
    from renewal.ratewatch.letter import _x
    assert _x("<b>") == "&lt;b&gt;"


# 5: live validation fails closed
def test_live_validation_fails_closed():
    good5 = [(60, "fixed_closed", "posted", 6.19)]
    anchor = {"boc_5y_posted": 6.19, "goc_5y": 3.55}
    assert live.validate(good5, "bank", anchor)[0]
    assert not live.validate(good5 + [(12, "fixed_closed", "posted", 55.0)], "bank", anchor)[0]
    assert not live.validate(good5 + [(12, "fixed_closed", "posted", -2.0)], "bank", anchor)[0]
    assert not live.validate([(60, "fixed_closed", "posted", -4.0)], "credit_union", {})[0]
    assert not live.validate(good5, "bank", {})[0]            # no reference figures -> refuse, never pass
    assert not live.validate([(60, "fixed_closed", "posted", 4.8), (12, "fixed_closed", "posted", 13.9)], "credit_union", anchor)[0]


# 6: reverse-rate returns every compatible interval
def test_reverse_rate_finds_both_sides_of_the_discount_fallback():
    m = mortgage(contract_rate=6.0, discount=2.0)
    q1 = penalty(m, TD, {t: 1.0 for t in TABLE}, DAY)["penalty"]
    q3 = penalty(m, TD, {t: 3.0 for t in TABLE}, DAY)["penalty"]
    assert abs(q1 - q3) < 0.01                                 # the reviewer's case: 1% and 3% give the same charge
    res = x.reverse_rate(m, TD, DAY, q1)
    hits = res["compatible_posted_rate_ranges"]
    assert any(lo <= 1.0 <= hi for lo, hi in hits) and any(lo <= 3.0 <= hi for lo, hi in hits)
    assert not res["unique"]


# 7: switching savings stop at the new offer's guaranteed term
def test_switch_uses_new_offer_term():
    m = mortgage()
    full = x.net_switch_benefit(m, TD, TABLE, DAY, 3.5, 0)
    capped = x.net_switch_benefit(m, TD, TABLE, DAY, 3.5, 0, new_term_months=12)
    assert capped["horizon_months"] == 12 and capped["interest_saved"] < full["interest_saved"]
    be = x.break_even(m, TD, TABLE, DAY, 3.5, 0, new_term_months=12)
    assert be["horizon_months"] == 12 and be["worth_it_within_remaining_term"] == capped["switch"]


# 8: formatting variants of one statement count once
def test_duplicate_detection_ignores_number_formatting(tmp_path, monkeypatch):
    monkeypatch.setattr(accuracy, "CASES", tmp_path / "c.csv")
    rows = []
    for bal, rate, pen in [("400000", "4.89", "12816"), ("400000.00", "4.890", "12816.00"), ("4e5", "4.8900", "12816.0")]:
        rows.append(["RBC", bal, rate, "60", "2023-10-15", "2026-10-14", "2.0", "", "24:5.29;36:6.05", "", pen, "stmt-1", "payout_statement"])
    with open(accuracy.CASES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(accuracy.HEADER)
        w.writerows(rows)
    assert len(accuracy.load_cases()) == 1


# 9: explicit month units in archived JSON
def test_archived_json_month_units():
    rows = backfill._walk_json({"r": [{"term_months": 6, "rate": 6.1}, {"term_months": 12, "rate": 5.9},
                                      {"term": "5 year", "rate": 6.2}, {"term": 3, "rate": 6.0}]}, [])
    terms = sorted(r[0] for r in rows)
    assert terms == [6, 12, 36, 60]


# 10: empty discovery is retried; rejections are tied to the parser version
def test_backfill_retries_empty_discovery_and_new_parser(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "PROGRESS", tmp_path / "p.json")
    monkeypatch.setattr(backfill, "COVERAGE", tmp_path / "c.json")
    monkeypatch.setattr(backfill, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(backfill, "SOURCES", {"P021": [("html", "https://example.test/r", "exact")]})
    monkeypatch.setattr(backfill, "months", lambda: ["202501"])
    monkeypatch.setattr(backfill.history, "official", lambda **k: 0)
    monkeypatch.setattr(backfill, "cc_crawls", lambda: [])
    calls = []
    monkeypatch.setattr(backfill, "captures", lambda arc, url, match: calls.append(1) or {})
    backfill.run()
    backfill.run()
    assert len(calls) == 2                                      # empty result was not cached


# 11: weekly comparison never uses observations after the BoC date
def test_weekly_backtest_has_no_lookahead(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "r.db")
    wed = date(2025, 1, 8)
    history.save("BIG6_TYPICAL", wed.isoformat(), [(60, "fixed_closed", "posted", 6.49)], "boc")
    for sid in ("P021", "P023", "P025"):
        history.save(sid, "2025-01-06", [(60, "fixed_closed", "posted", 6.49)], "html")       # Monday: valid
        history.save(sid, "2025-01-09", [(60, "fixed_closed", "posted", 6.29)], "html")       # Thursday: later
    r = backtest.scraped_vs_boc()
    assert r["weeks_with_3plus_banks"] >= 1 and r["mode_equals_boc"] >= 1


# 12: blank tables load recorded historical rates
def test_blank_table_uses_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "r.db")
    monkeypatch.setattr(accuracy, "CASES", tmp_path / "c.csv")
    history.save("P021", "2026-10-12", [(24, "fixed_closed", "posted", 5.74), (36, "fixed_closed", "posted", 6.25)], "html")
    with open(accuracy.CASES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(accuracy.HEADER)
        w.writerow(["RBC", "400000", "4.89", "60", "2023-10-15", "2026-10-14", "2.0", "", "", "", "12816", "s1", "payout_statement"])
    (case,) = accuracy.load_cases()
    assert case[3] == {24: 5.74, 36: 6.25}


# 13: impossible dates and tables are rejected
@pytest.mark.parametrize("change", [
    {"current_posted": {"24": -1.0}}, {"current_posted": {"24": 55}}, {"current_posted": {"999": 5.0}},
    {"maturity": "2020-01-01"}, {"payout": "2020-01-01"}, {"start": "1900-01-01"},
    {"maturity": "2999-01-01"}, {"payout": "9999-12-31"}])
def test_bad_dates_and_tables_rejected(change):
    assert client.post("/api/ratewatch/penalty", json={**BODY, **change}).status_code == 422


# 14: concurrent live refreshes collect once
def test_live_refresh_runs_one_collection_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "BOARD", tmp_path / "b.json")
    monkeypatch.setattr(live, "REFRESH_LOCK", tmp_path / "lock")
    started = []

    def slow(lenders=None):
        started.append(1)
        time.sleep(0.5)
        live.BOARD.write_text(json.dumps({"refreshed_at": "x", "banks": [], "credit_unions": []}))
        return json.loads(live.BOARD.read_text())
    monkeypatch.setattr(live, "_refresh", slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(live.refresh())) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(started) == 1 and len(out) == 3
    holder = open(tmp_path / "lock", "a+b")                  # another process holding the OS lock
    assert live._try_os_lock(holder)
    assert live.refresh().get("refreshed_at") == "x" and len(started) == 1
    live._os_unlock(holder)
    holder.close()
