"""Live rates board: every tier, validation, and the API. No network."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import history, live

ORIGINAL_REDISCOVER = live.read_rediscovered          # captured before fixtures replace it
ANCHOR = {"boc_5y_posted": 6.19, "boc_5y_posted_date": "2026-10-14", "goc_5y": 3.55}
GOOD_BANK = [(60, "fixed_closed", "posted", 6.19), (60, "fixed_closed", "special", 5.14), (36, "fixed_closed", "posted", 6.25)]
GOOD_CU = [(60, "fixed_closed", "posted", 4.84)]
BANK = ("T001", "Test Bank", "bank", ("html", "https://bank.test/rates"), None)
BANK_B1 = ("T002", "Test Bank 2", "bank", ("html", "https://bank2.test/rates"), ("html", "https://bank2.test/fr/taux"))
CU = ("T003", "Test CU", "credit_union", ("html", "https://cu.test/rates"), None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(live, "BOARD", tmp_path / "board.json")
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(live, "read_rediscovered", lambda url: ([], None))
    monkeypatch.setattr(live, "read_archive", lambda kind, url: ([], "no archive copy"))


def boom(*a, **k):
    raise TimeoutError("down")


def test_primary_used_and_cached(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK)
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "primary" and r["five_year"]["posted"] == 6.19 and r["five_year"]["special"] == 5.14
    assert json.loads(live.CACHE.read_text())["T001"]["rows"]


def test_backup1_second_live_source(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK if "/fr/" in url else boom())
    r = live.resolve(BANK_B1, ANCHOR)
    assert r["tier"] == "backup1" and r["source_url"].endswith("/fr/taux")


def test_backup1_rediscovery_when_no_second_source(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: (GOOD_BANK, "https://bank.test/new-rates"))
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "backup1" and any("rediscovered" in t["reason"] for t in r["tried"])


def test_backup2_last_good_reading(monkeypatch):
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK)
    live.resolve(BANK, ANCHOR)
    monkeypatch.setattr(live, "read_live", boom)
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "cache" and r["five_year"]["posted"] == 6.19


def test_cache_older_than_limit_is_not_used(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=live.CACHE_DAYS + 1)).isoformat()
    live.CACHE.write_text(json.dumps({"T001": {"at": old, "tier": "primary", "url": "x", "rows": GOOD_BANK}}))
    monkeypatch.setattr(live, "read_live", boom)
    assert live.resolve(BANK, ANCHOR)["tier"] != "cache"


def test_backup3_archive(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    monkeypatch.setattr(live, "read_archive", lambda kind, url: (GOOD_BANK, "wayback 20261014"))
    r = live.resolve(BANK, ANCHOR)
    assert r["tier"] == "archive" and r["as_of"] == "wayback 20261014"


def test_all_fail_bank_shows_labelled_boc_and_cu_shows_unavailable(monkeypatch):
    monkeypatch.setattr(live, "read_live", boom)
    b = live.resolve(BANK, ANCHOR)
    assert b["tier"] == "boc_typical" and b["lender_specific"] is False and b["five_year"]["posted"] == 6.19
    c = live.resolve(CU, ANCHOR)
    assert c["tier"] == "unavailable" and c["five_year"]["advertised"] is None
    assert [t["tier"] for t in c["tried"]] == ["primary", "backup1", "cache", "archive"]


def test_validation_rejects_bad_readings_and_moves_on(monkeypatch):
    far = [(60, "fixed_closed", "posted", 9.99)]                         # far from the BoC big-six figure
    swapped = [(60, "fixed_closed", "posted", 4.49), (60, "fixed_closed", "special", 6.49)]
    assert not live.validate(far, "bank", ANCHOR)[0]
    assert not live.validate(swapped, "bank", ANCHOR)[0]
    assert not live.validate([(60, "fixed_closed", "posted", 3.10)], "credit_union", ANCHOR)[0]   # below bond + 0.3
    assert live.validate(GOOD_CU, "credit_union", ANCHOR)[0]
    calls = iter([far, GOOD_BANK])
    monkeypatch.setattr(live, "read_live", lambda kind, url: next(calls))
    r = live.resolve(BANK_B1, ANCHOR)
    assert r["tier"] == "backup1" and r["tried"][0]["ok"] is False


def test_refresh_and_api(monkeypatch):
    monkeypatch.setattr(live, "market_anchor", lambda: ANCHOR)
    monkeypatch.setattr(live, "LENDERS", [BANK, CU])
    monkeypatch.setattr(live, "read_live", lambda kind, url: GOOD_BANK if "bank" in url else GOOD_CU)
    client = TestClient(app)
    b = client.post("/api/ratewatch/live/refresh").json()
    assert [r["name"] for r in b["banks"]] == ["Test Bank"] and b["credit_unions"][0]["five_year"]["advertised"] == 4.84
    again = client.get("/api/ratewatch/live").json()
    assert again["refreshed_at"] == b["refreshed_at"] and again["stale"] is False


def test_alternative_lenders_validate_with_wider_band():
    anchor = {"boc_5y_posted": 6.19, "goc_5y": 3.55}
    assert live.validate([(60, "fixed_closed", "posted", 9.99)], "alternative", anchor)[0]       # B/private pricing
    assert not live.validate([(60, "fixed_closed", "posted", 9.99)], "credit_union", anchor)[0]
    assert not live.validate([(60, "fixed_closed", "posted", 14.9)], "alternative", anchor)[0]


def test_registry_is_banks_credit_unions_and_30_alternative_lenders():
    assert {t for _, _, t, _, _ in live.LENDERS} == {"bank", "credit_union", "alternative"}
    assert sum(t == "alternative" for _, _, t, _, _ in live.LENDERS) == 30
    assert sum(t == "bank" for _, _, t, _, _ in live.LENDERS) == 6


def test_sub_brand_rediscovery_never_takes_parent_bank_rates(monkeypatch):
    from renewal.ratewatch import scrape
    url = "https://www.nbc.ca/en/optimummortgage/brokers/rates.html"
    monkeypatch.setattr(live, "read_rediscovered", ORIGINAL_REDISCOVER)
    monkeypatch.setattr(scrape, "rediscovered", lambda u: (GOOD_BANK, "https://www.nbc.ca/personal/mortgages/rates.html"))
    assert live.read_rediscovered(url) == ([], None)
    monkeypatch.setattr(scrape, "rediscovered", lambda u: (GOOD_BANK, "https://www.nbc.ca/en/optimummortgage/rates-2.html"))
    assert live.read_rediscovered(url)[0] == GOOD_BANK
