"""One regression test per defect found in the October 14 review."""
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.ratewatch import accuracy, backfill, extras as x, history
from renewal.ratewatch.ird import Mortgage, POLICIES, add_months, forecast, penalty
from renewal.ratewatch.parse import extract_rates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import package_zip  # noqa: E402

client = TestClient(app)
TD = POLICIES["TD"]
TABLE = {6: 5.54, 12: 5.49, 24: 5.29, 36: 6.05, 48: 5.99, 60: 6.09, 72: 6.29, 84: 6.4, 120: 6.8}
DAY = date(2026, 10, 14)


def mortgage(**kw):
    base = dict(balance=400_000, contract_rate=4.89, term_months=60, start=date(2023, 10, 15), discount=2.0,
                maturity=date(2028, 10, 15))
    base.update(kw)
    return Mortgage(**base)


# 1 + 2: verification needs real, distinct, held-out evidence; TD's rules are locked
def _write_cases(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(accuracy.HEADER)
        w.writerows(rows)


def test_duplicated_or_synthetic_cases_never_verify(tmp_path, monkeypatch):
    monkeypatch.setattr(accuracy, "CASES", tmp_path / "cases.csv")
    monkeypatch.setattr(accuracy, "CAL", tmp_path / "cal.json")
    row = ["RBC", "400000", "4.89", "60", "2023-10-15", "2026-10-14", "2.0", "", "24:5.29;36:6.05", "", "12816", "case-1"]
    _write_cases(accuracy.CASES, [row + ["synthetic"]] * 10 + [row + ["payout_statement"]] * 10)
    assert len(accuracy.load_cases()) == 1                       # synthetic ignored, duplicates counted once
    accuracy.run()
    cal = json.loads(accuracy.CAL.read_text())
    assert not cal.get("RBC", {}).get("verified", False)


def test_calibration_cannot_replace_td_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(accuracy, "CAL", tmp_path / "cal.json")
    accuracy.CAL.write_text(json.dumps({"TD": {"lender": "TD", "comparison": "posted", "term_match": "nearest", "verified": True}}))
    p = accuracy.policy_for("TD")
    assert p is TD and p.term_match == "bands" and p.months_convention == "td"


# 3: a table with Special and Posted columns
def test_special_and_posted_columns_are_not_swapped():
    html = ("<table><tr><th>Term</th><th>Special offer</th><th>Posted rate</th><th>APR</th></tr>"
            "<tr><td>5 Year Fixed Closed</td><td>4.49%</td><td>6.49%</td><td>4.52%</td></tr></table>")
    rows = extract_rates(html)
    assert (60, "fixed_closed", "posted", 6.49) in rows and (60, "fixed_closed", "special", 4.49) in rows
    assert (60, "fixed_closed", "posted", 4.49) not in rows


# 4: units in embedded JSON
def test_term_months_is_not_rescaled():
    rows = extract_rates('<script>var d={"a":[{"term_months": 60, "rate": "6.19", "kind": "posted"}]}</script>')
    assert rows == [(60, "fixed_closed", "posted", 6.19)]


# 5: month arithmetic
def test_add_months_keeps_month_end():
    assert add_months(date(2026, 10, 31), 0) == date(2026, 10, 31)
    assert add_months(date(2026, 10, 31), 1) == date(2026, 11, 30)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


# 6: forecast respects the supplied maturity
def test_forecast_stops_at_supplied_maturity():
    m = mortgage(maturity=date(2027, 3, 1))                       # earlier than start + 60 months
    rows = forecast(m, TD, TABLE, DAY)
    assert rows and max(r["payout"] for r in rows) < "2027-03-01"


# 7: amortization is an input
def test_amortization_changes_projection():
    a = x.heatmap(mortgage(amort_months=300), TD, TABLE, DAY, months_ahead=6)["rows"][6]["balance_assumed"]
    b = x.heatmap(mortgage(amort_months=120), TD, TABLE, DAY, months_ahead=6)["rows"][6]["balance_assumed"]
    assert b < a
    body = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
            "maturity": "2028-10-15", "discount": 2.0, "payout": "2026-10-14", "amort_months": 120,
            "current_posted": {str(k): v for k, v in TABLE.items()}}
    assert client.post("/api/ratewatch/penalty", json=body).status_code == 200


# 8: decisions never contradict
def test_break_even_and_net_switch_always_agree():
    rng = random.Random(11)
    for _ in range(200):
        m = mortgage(balance=rng.uniform(100_000, 900_000), contract_rate=rng.uniform(3, 7.5), discount=rng.uniform(0, 2))
        new = rng.uniform(2, 7)
        fees = rng.uniform(0, 3000)
        be, ns = x.break_even(m, TD, TABLE, DAY, new, fees), x.net_switch_benefit(m, TD, TABLE, DAY, new, fees)
        assert be["worth_it_within_remaining_term"] == ns["switch"]


# 9: reverse-rate finds off-grid answers
def test_reverse_rate_finds_5_291():
    m = mortgage()
    quote = penalty(m, TD, {**TABLE, 24: 5.291}, DAY)["penalty"]
    (lo, hi), = x.reverse_rate(m, TD, DAY, quote)["compatible_posted_rate_ranges"]
    assert lo <= 5.291 <= hi


# 10: conflicting captures are reported
def test_conflicting_captures_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "r.db")
    history.save("P021", "2025-01-08", [(60, "fixed_closed", "posted", 6.49)], "html")
    history.save("P021", "2025-01-08", [(60, "fixed_closed", "posted", 6.29)], "wayback")
    c = history.conflicts()
    assert len(c) == 1 and {c[0][6], c[0][8]} == {6.49, 6.29}


# 11: transient download failures stay retryable
def test_backfill_does_not_mark_failed_downloads_done(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "PROGRESS", tmp_path / "p.json")
    monkeypatch.setattr(backfill, "COVERAGE", tmp_path / "c.json")
    monkeypatch.setattr(backfill, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(backfill, "SOURCES", {"P021": [("html", "https://example.test/rates", "exact")]})
    monkeypatch.setattr(backfill, "months", lambda: ["202501"])
    monkeypatch.setattr(backfill.history, "official", lambda **k: 0)
    monkeypatch.setattr(backfill, "cc_crawls", lambda: [])                 # no network in tests
    monkeypatch.setattr(backfill, "captures", lambda arc, url, match: {"202501": [("20250108000000", url)]})

    class Fail:
        status_code, ok, text = 503, False, ""
    monkeypatch.setattr(backfill.Archive, "get", lambda self, url, params=None, timeout=120: Fail())
    backfill.run()
    assert "20250108000000" not in json.loads(backfill.PROGRESS.read_text()).get("tried:P021", [])


# 12: client name stays out of URLs
def test_letter_takes_client_name_in_body_only():
    body = {"lender": "TD", "balance": 400000, "contract_rate": 4.89, "term_months": 60, "start": "2023-10-15",
            "maturity": "2028-10-15", "discount": 2.0, "payout": "2026-10-14", "client_name": "Private Person",
            "current_posted": {str(k): v for k, v in TABLE.items()}}
    assert client.post("/api/ratewatch/letter", json=body).status_code == 200
    from renewal.ratewatch import api
    assert "client_name" not in str(api.letter.__code__.co_varnames[:api.letter.__code__.co_argcount])


# 13 + 14: packaging
def test_zip_rules_keep_dotfiles_and_drop_databases():
    assert package_zip.included(".github/workflows/ci.yml") and package_zip.included(".gitignore")
    assert package_zip.included(".env.example")
    for rel in ("data/broker-workspaces.sqlite3", "renewal_radar.db", "data/ratewatch/rates.db",
                "data/ratewatch/td_oracle/td-prepayment.min.js", ".venv/Lib/site.py"):
        assert not package_zip.included(rel), rel
