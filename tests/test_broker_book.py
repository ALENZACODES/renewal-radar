"""Broker book review: ingest from different software layouts, review maths, API. No network (board injected)."""
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from renewal.main import app
from renewal.broker import book_ingest as bi, book_review as br
from renewal.ratewatch import history

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TD_TABLE = [(6, 5.54), (12, 5.49), (24, 5.29), (36, 6.05), (48, 5.99), (60, 6.09), (72, 6.29), (84, 6.4), (120, 6.8)]
BOARD = {"banks": [{"name": "RBC", "lender_specific": True, "as_of": "2026-10-15", "tier_label": "Live",
                    "rates": {"60": {"posted": 6.19, "special": 4.40}}}],
         "credit_unions": [{"name": "Unlabelled CU", "lender_specific": True, "as_of": "2026-10-15", "tier_label": "Live",
                            "rates": {"60": {"posted": 3.85}}},
                           {"name": "Good CU", "lender_specific": True, "as_of": "2026-10-15", "tier_label": "Live",
                            "rates": {"60": {"posted": 6.49, "special": 4.60}}}]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db")
    monkeypatch.setattr(br, "_board", lambda: BOARD)
    history.save("P023", "2026-10-14", [(t, "fixed_closed", "posted", r) for t, r in TD_TABLE], "api")


# ---------------- ingest: different software layouts ----------------
LAYOUTS = {
    "lender-system style": "Deal #,Applicant Name,Lender,Net Rate,Term,Closing Date,Maturity Date,Total Mortgage Amount,Amortization\n"
                           "D1,Client A,TD Canada Trust,5.84,60,2023-10-16,2028-10-16,520000,25\n",
    "online-application style": "Application ID,Client,Funder,Rate,Term (Years),Funded Date,Loan Amount,Amortization (years),Rate Type\n"
                                "A9,Client B,TD,5.84%,5,10/16/2023,\"$520,000.00\",25,Fixed\n",
    "crm export, semicolon, day-first": "Reference;Borrower;Bank;Interest Rate;Term months;IAD;Current Balance;Amortization months\n"
                                        "R7;Client C;TD;5,84;60;16/10/2023;498000;276\n",
    "tab separated": "Loan Number\tCustomer\tInstitution\tContract Rate\tMortgage Term\tAdvance Date\tOutstanding Balance\n"
                     "L3\tClient D\tTD\t0.0584\t5 years\t2023-10-16\t498000\n",
}


@pytest.mark.parametrize("name", list(LAYOUTS))
def test_imports_common_layouts(name):
    r = bi.import_csv(LAYOUTS[name].encode())
    d = r["deals"][0]
    assert d["lender"] and "td" in d["lender"].lower()
    assert d["contract_rate"] == 5.84
    assert d["closing_date"] == "2023-10-16" and d["maturity_date"] == "2028-10-16"
    assert d["term_months"] == 60
    assert d["balance"] in (520000.0, 498000.0)


def test_balance_basis_and_amortization_units():
    a = bi.import_csv(LAYOUTS["lender-system style"].encode())["deals"][0]
    c = bi.import_csv(LAYOUTS["crm export, semicolon, day-first"].encode())
    assert a["balance_basis"] == "original" and a["amort_months"] == 300
    assert c["deals"][0]["balance_basis"] == "current" and c["deals"][0]["amort_months"] == 276
    assert c["date_order"] == "day/month/year"


def test_unreadable_values_are_flagged_not_guessed():
    r = bi.import_csv(b"Deal ID,Lender,Rate,Closing Date,Term\nX1,TD,abc,someday,60\n")
    d = r["deals"][0]
    assert d["contract_rate"] is None and d["closing_date"] is None
    assert any("missing contract rate" in i for i in d["issues"])
    assert "balance" in r["unmapped_fields"]


def test_mapping_overrides_and_ignored_columns():
    r = bi.import_csv(b"Ref,Who,Funder,Pct,Start,End,Owing,Notes\nZ,Q,TD,5.5,2024-01-01,2029-01-01,300000,hello\n",
                      overrides={"contract_rate": "Pct", "closing_date": "Start", "maturity_date": "End", "balance": "Owing"})
    d = r["deals"][0]
    assert d["contract_rate"] == 5.5 and d["balance"] == 300000.0 and "Notes" in r["ignored_columns"]


def test_json_pipeline_and_ocr_conversion():
    payload = {"deals": [{"loan_number": "J1", "lender": "TD", "interest_rate": "5.84", "term_months": 60,
                          "funding_date": "2023-10-16", "mortgage_amount": 520000}]}
    d = bi.import_json(json.dumps(payload))["deals"][0]
    assert d["deal_id"] == "J1" and d["maturity_date"] == "2028-10-16"
    ocr = {"fields": {"balance": {"value": "498,000.00", "page": 1, "excerpt": "Balance $498,000.00"},
                      "current_rate": {"value": "5.84", "page": 1, "excerpt": "rate 5.84%"},
                      "maturity_date": {"value": "2028-10-16", "page": 1, "excerpt": "matures"}}}
    o = bi.deal_from_ocr(ocr, "doc-1", lender="TD", closing_date="2023-10-16")
    assert o["balance"] == 498000.0 and o["source"] == "ocr" and o["issues"][0].startswith("read by OCR")
    assert o["evidence"]["balance"]["page"] == 1


def test_sample_fixture_imports_cleanly():
    r = bi.import_csv((ROOT / "fixtures" / "broker-book-sample.csv").read_bytes())
    assert r["rows"] == 8 and r["ignored_columns"] == [] and r["unmapped_fields"] == []


# ---------------- review ----------------
def deal(**kw):
    base = {"deal_id": "D1", "borrower": "Client", "lender": "TD Canada Trust", "rate_type": "fixed", "balance": 500000,
            "contract_rate": 6.5, "posted_rate": 8.0, "term_months": 60, "closing_date": "2023-10-16",
            "maturity_date": "2028-10-16", "amort_months": 300}
    base.update(kw)
    return base


def test_default_offer_is_labelled_special_rate_not_unlabelled_number():
    offers = br.best_offers(60)
    assert offers[0]["lender"] == "RBC" and offers[0]["rate"] == 4.40
    assert all(o["labelled"] for o in offers)


def test_td_deal_uses_exact_engine_and_ranks():
    rv = br.review_book([deal(), deal(deal_id="D2", contract_rate=4.5)], as_of=date(2026, 10, 15))
    top = rv["results"][0]
    assert top["deal_id"] == "D1" and top["method_status"] == "exact-method"
    assert top["penalty"]["penalty"] > 0 and top["best_offer"]["rate"] == 4.40
    assert top["net_benefit"] == pytest.approx(top["interest_saved"] - top["penalty"]["penalty"], abs=0.02)
    assert rv["results"][1]["status"] == "no_opportunity"


def test_missing_discount_gives_floor_only():
    r = br.review_book([deal(posted_rate=None)], as_of=date(2026, 10, 15))["results"][0]
    assert r["status"] == "needs_data" and r["three_month_floor"] > 0 and "discount" in r["recommendation"]


def test_discount_from_recorded_posted_rate_on_closing_date():
    history.save("P023", "2023-10-10", [(60, "fixed_closed", "posted", 7.49)], "wayback")
    r = br.review_book([deal(posted_rate=None)], as_of=date(2026, 10, 15))["results"][0]
    assert r["status"] != "needs_data" and any("recorded posted rate" in i for i in r["issues"])


def test_unknown_lender_rates_flagged_and_variable_three_month():
    rv = br.review_book([deal(lender="MCAP"), deal(deal_id="V", lender="RBC", rate_type="variable")], as_of=date(2026, 10, 15))
    by = {r["deal_id"]: r for r in rv["results"]}
    assert by["D1"]["status"] == "needs_data"
    assert by["V"]["penalty"]["method"] == "3-month (variable)" and by["V"]["method_status"] == "estimate"


def test_original_amount_projected_to_today():
    r = br.review_book([deal(balance_basis="original")], as_of=date(2026, 10, 15))["results"][0]
    assert br.review_book([deal()], as_of=date(2026, 10, 15))["results"][0]["balance_today"] == 500000   # stated = as is
    assert r["balance_today"] < 500000 and "projected" in r["balance_basis"]


def test_filters_by_closing_window_and_lender():
    ds = [deal(deal_id="old", closing_date="2021-06-01", maturity_date="2026-12-01"), deal(deal_id="new")]
    rv = br.review_book(ds, as_of=date(2026, 10, 15), closed_from=date(2023, 1, 1), closed_to=date(2023, 12, 31), lender="td")
    assert [r["deal_id"] for r in rv["results"]] == ["new"]


def test_matured_not_started_and_renewal_window():
    rv = br.review_book([deal(deal_id="m", closing_date="2021-09-01", maturity_date="2026-09-01"), deal(deal_id="f", closing_date="2027-01-01", maturity_date="2032-01-01"),
                         deal(deal_id="w", closing_date="2021-12-15", maturity_date="2026-12-15")], as_of=date(2026, 10, 15))
    st = {r["deal_id"]: r["status"] for r in rv["results"]}
    assert st["m"] == "matured" and st["f"] == "not_started" and st["w"] == "renewal_window"


def test_target_rate_override_and_years_saved():
    r = br.review_book([deal()], as_of=date(2026, 10, 15), target_rate=3.9)["results"][0]
    assert r["best_offer"]["lender"] == "broker target" and r["years_saved_same_payment"] > 0


# ---------------- API ----------------
def test_api_import_review_csv_and_sample():
    s = client.get("/api/broker/book/sample.csv")
    assert s.status_code == 200 and "File Number" in s.text
    imp = client.post("/api/broker/book/import", files={"file": ("book.csv", s.content, "text/csv")}).json()
    assert len(imp["deals"]) == 8
    rv = client.post("/api/broker/book/review", json={"deals": imp["deals"], "as_of": "2026-10-15"}).json()
    assert rv["deals_reviewed"] == 8 and rv["results"]
    csv_r = client.post("/api/broker/book/review.csv", json={"deals": imp["deals"], "as_of": "2026-10-15"})
    assert csv_r.status_code == 200 and csv_r.text.startswith("status,deal_id")


def test_api_rejects_bad_input():
    assert client.post("/api/broker/book/review", json={"deals": []}).status_code == 422
    assert client.post("/api/broker/book/review", json={"deals": [deal()], "target_rate": 99}).status_code == 422
    assert client.post("/api/broker/book/import", files={"file": ("x.csv", b"", "text/csv")}).status_code == 422
