"""Ratewatch integration tests: no network. Lender feeds are tested with recorded response shapes."""
import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import backtest, scrape
from renewal.ratewatch.ird import POLICIES
from renewal.ratewatch.ontario import ONTARIO
from renewal.ratewatch.registry import CHECKS, PRIMARY

client = TestClient(app)
TD_TABLE = {"6": 5.54, "12": 5.49, "24": 5.29, "36": 6.05, "48": 5.99, "60": 6.09, "72": 6.29, "84": 6.4, "120": 6.8}
BODY = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
        "maturity": "2028-10-15", "discount": 2.0, "payout": "2026-10-14", "current_posted": TD_TABLE}


def test_registry_has_100_sources_100_checks_100_ontario_lenders():
    assert len(PRIMARY) == 100 and len(CHECKS) == 100 and len(ONTARIO) == 100
    ids = [r[0] for r in PRIMARY + CHECKS + ONTARIO]
    assert len(ids) == len(set(ids))
    assert all(r[4].startswith("http") for r in PRIMARY) and all(r[3].startswith("http") for r in CHECKS)


def test_letterhead_has_no_brokerage_or_licence_fields():
    from renewal.ratewatch.letter import BROKER
    assert BROKER["name"] == "Renewal Radar" and BROKER["title"] == "Alenza Fintech"
    assert not any(BROKER[k] for k in ("brokerage", "brokerage_no", "licence", "phone"))


def test_penalty_endpoint_matches_td_calculator():
    r = client.post("/api/ratewatch/penalty", json=BODY)
    assert r.status_code == 200
    j = r.json()
    assert j["ird"] == 12832.00 and j["three_month"] == 4890.00 and j["compare_term"] == 24
    assert j["status"] == "exact-method" and j["rates_source"] == "supplied"


def test_penalty_endpoint_validates_input():
    assert client.post("/api/ratewatch/penalty", json={**BODY, "balance": -5}).status_code == 422


def test_forecast_endpoint_reports_transition_points():
    j = client.post("/api/ratewatch/forecast", json=BODY).json()
    assert [t["compare_term"] for t in j["transitions"]][:2] == [12, 6]


def test_letter_endpoint_returns_one_page_pdf():
    import pymupdf
    r = client.post("/api/ratewatch/letter", json={**BODY, "client_name": "Alex Sample"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = doc[0].get_text()
    assert doc.page_count == 1 and "$12,832.00" in text and "Alenza Fintech" in text


def test_scotia_feed_parser():
    js = {"data": [{"PRODUCT": "CONVENTIONAL RESIDENTIAL, ETC", "TERMS": [
        {"TERM_VALUE": "5", "TERM_UNIT": "Y", "RATE": 6.19}, {"TERM_VALUE": "6", "TERM_UNIT": "M", "RATE": 5.95}]},
        {"PRODUCT": "N.H.A. RESIDENTIAL, ETC", "TERMS": [{"TERM_VALUE": "5", "TERM_UNIT": "Y", "RATE": 6.19}]}]}
    rows = scrape.scotia_rows(js)
    assert (60, "fixed_closed", "posted", 6.19) in rows and (6, "fixed_closed", "posted", 5.95) in rows
    assert (60, "fixed_closed", "posted_insured", 6.19) in rows


def test_bmo_feed_parser_skips_convertible():
    js = {"mortgageRates": {"fixed": {
        "5YearClosed": {"en": "5 year (closed)", "value": "6.090", "term_months": "60"},
        "6MonthConvertible": {"en": "6 month (convertible)", "value": "5.490", "term_months": "6"},
        "1YearOpen": {"en": "1 year (open)", "value": "9.950", "term_months": "12"}}}}
    rows = scrape.bmo_posted_rows(js)
    assert rows == [(60, "fixed_closed", "posted", 6.09), (12, "open", "posted", 9.95)]


def test_dedupe_keeps_first_value():
    assert scrape._dedupe([(60, "fixed_closed", "posted", 6.19), (60, "fixed_closed", "posted", 6.0)]) == [(60, "fixed_closed", "posted", 6.19)]


TD_JS = backtest.DATA / "td_oracle" / "td-prepayment.min.js"


@pytest.mark.skipif(shutil.which("node") is None or not TD_JS.exists(),
                    reason="needs Node.js and TD's calculator file (python tools/fetch_td_oracle.py)")
def test_td_oracle_200_random_cases_exact_to_the_cent():
    r = backtest.td_oracle(n=200, seed=7)
    assert r["exact_to_the_cent"] == 200, r["examples_of_misses"][:2]


def test_td_policy_is_marked_verified_and_others_are_not():
    assert POLICIES["TD"].verified
    assert not POLICIES["RBC"].verified and not POLICIES["BMO"].verified


# ---- regressions found in review (2026-10-14) ----
def test_no_penalty_at_or_after_maturity():
    from renewal.ratewatch.ird import Mortgage, penalty
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.0, maturity=date(2028, 10, 15))
    table = {int(k): v for k, v in TD_TABLE.items()}
    for day in (date(2028, 10, 15), date(2029, 1, 1)):
        r = penalty(m, POLICIES["TD"], table, day)
        assert r["penalty"] == 0 and r["three_month"] == 0 and r["method"] == "matured"
    assert client.post("/api/ratewatch/penalty", json={**BODY, "payout": "2028-10-15"}).json()["penalty"] == 0
    assert client.post("/api/ratewatch/letter", json={**BODY, "payout": "2028-10-15"}).status_code == 422


def test_td_never_substitutes_a_different_term_rate():
    from renewal.ratewatch.ird import Mortgage, penalty
    m = Mortgage(400_000, 4.89, 60, date(2023, 10, 15), discount=2.0, maturity=date(2028, 10, 15))
    table = {int(k): v for k, v in TD_TABLE.items() if k != "24"}       # TD needs the 2-year rate here
    with pytest.raises(ValueError, match="24-month"):
        penalty(m, POLICIES["TD"], table, date(2026, 10, 14))
    r = client.post("/api/ratewatch/penalty", json={**BODY, "current_posted": {k: v for k, v in TD_TABLE.items() if k != "24"}})
    assert r.status_code == 422 and "24-month" in r.text


def test_letter_endpoint_writes_nothing_to_disk(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    before = set(tmp_path.iterdir())
    r = client.post("/api/ratewatch/letter", json={**BODY, "client_name": "Private Person"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert set(tmp_path.iterdir()) == before


def test_history_never_mixes_two_captures_from_the_same_day(tmp_path, monkeypatch):
    from renewal.ratewatch import history
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    history.save("P099", "2024-05-01", [(60, "fixed_closed", "posted", 6.79), (36, "fixed_closed", "posted", 6.50)], "wayback")
    history.save("P099", "2024-05-01", [(60, "fixed_closed", "posted", 6.80)], "api")
    table, day = history.table_on("P099", date(2024, 5, 10))
    assert day == "2024-05-01" and table == {60: 6.80}            # the feed wins; no archive row mixed in
    assert history.table_on("P099", date(2024, 4, 30)) == ({}, None)   # nothing from the future (no hindsight)
