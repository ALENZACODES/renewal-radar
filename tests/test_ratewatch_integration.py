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


SCOTIA_JS = backtest.DATA / "scotia_oracle" / "main.js"


@pytest.mark.skipif(shutil.which("node") is None or not SCOTIA_JS.exists(),
                    reason="needs Node.js and Scotiabank's calculator files (python tools/fetch_scotia_oracle.py)")
def test_scotia_oracle_300_random_cases_exact_to_the_cent():
    r = backtest.scotia_oracle(n=300, seed=11)
    assert r["exact_to_the_cent"] == 300, r["examples_of_misses"][:2]


def test_scotia_rules_from_its_calculator():
    from datetime import date
    from renewal.ratewatch.ird import Mortgage, add_months, penalty
    today = date(2026, 10, 15)
    table = {6: 5.95, 12: 5.49, 24: 5.24, 36: 6.05, 48: 6.09, 60: 6.19, 84: 6.4, 120: 6.8}
    mat = add_months(today, 24)
    r = penalty(Mortgage(400000, 4.89, 60, mat, discount=2.0, maturity=mat), POLICIES["Scotiabank"], table, today)
    assert r["penalty"] == 13200.0 and r["compare_term"] == 24
    # comparison rate 3+ points above the contract rate: Scotiabank's code charges nothing
    r = penalty(Mortgage(400000, 2.0, 60, mat, discount=0.0, maturity=mat), POLICIES["Scotiabank"], table, today)
    assert r["penalty"] == 0.0
    # 10-year term with 5+ years elapsed: three months' interest only
    mat = add_months(today, 50)
    r = penalty(Mortgage(400000, 7.0, 120, mat, discount=0.0, maturity=mat), POLICIES["Scotiabank"], table, today)
    assert r["penalty"] == 7000.0


CIBC_JS = backtest.DATA / "cibc_oracle" / "mortgageprepayment.min.js"


@pytest.mark.skipif(shutil.which("node") is None or not CIBC_JS.exists(),
                    reason="needs Node.js and CIBC's calculator file (python tools/fetch_cibc_oracle.py)")
def test_cibc_oracle_300_random_cases_exact_to_the_cent():
    r = backtest.cibc_oracle(n=300, seed=13)
    assert r["exact_to_the_cent"] == 300, r["examples_of_misses"][:2]


def test_cibc_rules_from_its_calculator():
    from datetime import date
    from renewal.ratewatch.ird import Mortgage, penalty
    today, mat = date(2026, 10, 15), date(2028, 10, 15)
    table = {6: 6.0, 12: 6.1, 24: 5.5, 36: 6.05, 48: 6.09, 60: 6.19, 84: 6.4, 120: 6.8}
    m = Mortgage(400000, 4.89, 60, mat, discount=1.5, maturity=mat, payment=2300)
    r = penalty(m, POLICIES["CIBC"], table, today)     # same case run through CIBC's own code: 7,599.14 IRD
    assert r["penalty"] == 7599.14 and r["method"] == "IRD" and r["compare_term"] == 24
    near = date(2026, 12, 15)                           # under 3 months left: interest to maturity
    r = penalty(Mortgage(400000, 4.89, 60, near, discount=1.5, maturity=near, payment=2300), POLICIES["CIBC"], table, today)
    assert r["method"] == "maturity"


BMO_JS = backtest.DATA / "bmo_oracle" / "app.js"
NBC_JS = backtest.DATA / "nbc_oracle" / "fixed_total.js"


@pytest.mark.skipif(shutil.which("node") is None or not BMO_JS.exists(),
                    reason="needs Node.js and BMO's calculator bundle (python tools/fetch_bmo_oracle.py)")
def test_bmo_oracle_300_random_cases_exact_to_the_cent():
    r = backtest.bmo_oracle(n=300, seed=17)
    assert r["exact_to_the_cent"] == 300, r["examples_of_misses"][:2]


@pytest.mark.skipif(shutil.which("node") is None or not NBC_JS.exists(),
                    reason="needs Node.js and National Bank's form script (python tools/fetch_nbc_oracle.py)")
def test_nbc_oracle_300_random_cases_exact_to_the_cent():
    r = backtest.nbc_oracle(n=300, seed=19)
    assert r["exact_to_the_cent"] == 300, r["examples_of_misses"][:2]


def test_bmo_rules_from_its_calculator():
    from datetime import date
    from renewal.ratewatch.ird import Mortgage, add_months, penalty
    today = date(2026, 10, 15)
    table = {6: 6.0, 12: 6.1, 24: 5.5, 36: 6.05, 48: 6.09, 60: 6.19, 72: 6.3, 84: 6.4, 120: 6.8}
    mat = add_months(today, 30)                         # exactly between 2 and 3 years: BMO takes the higher posted rate
    r = penalty(Mortgage(400000, 4.89, 60, mat, discount=2.0, maturity=mat), POLICIES["BMO"], table, today)
    assert r["compare_posted"] == 6.05 and r["penalty"] == 8400.0
    mat = add_months(today, 2)                          # 2 months left: BMO prorates the charge to 2/3
    r = penalty(Mortgage(400000, 6.0, 60, mat, discount=0.0, maturity=mat), POLICIES["BMO"], table, today)
    assert r["penalty"] == round(400000 * 6.0 / 4 / 100 / 3 * 2, 2)


def test_nbc_rules_from_its_calculator():
    from datetime import date
    from renewal.ratewatch.ird import Mortgage, add_months, penalty
    today = date(2026, 10, 15)
    table = {6: 6.0, 12: 6.1, 24: 5.5, 36: 6.05, 48: 6.09, 60: 6.19, 84: 6.4, 120: 6.8}
    mat = add_months(today, 24)
    r = penalty(Mortgage(400000, 6.5, 60, mat, discount=2.0, maturity=mat), POLICIES["National Bank"], table, today)
    # (6.5% - 5.5% posted, no discount add-back) * 400k / 12 * 24 + one month's interest capped at $500
    assert r["penalty"] == round(400000 * 0.01 / 12 * 24 + 500, 2)


def test_td_policy_is_marked_verified_and_others_are_not():
    assert all(POLICIES[b].verified for b in ("TD", "Scotiabank", "CIBC", "BMO", "National Bank"))
    assert not POLICIES["RBC"].verified


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
