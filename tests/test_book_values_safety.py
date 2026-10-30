import json
from datetime import date, datetime

import pytest

from renewal.broker import book_ingest as ingest
from renewal.broker import book_values as values


@pytest.mark.parametrize("raw,expected", [
    ("$400,000.00", 400000),
    ("CAD 400000,00", 400000),
    ("400 000,50", 400000.5),
    ("400\u00a0000,50", 400000.5),
    ("400\u202f000,50", 400000.5),
    ("400.000,50", 400000.5),
    ("400,000.50", 400000.5),
    ("1,250", 1250),
    ("1250,5", 1250.5),
    ("1250.50", 1250.5),
    (1250, 1250),
    (1250.5, 1250.5),
    ("cad 1250.50", 1250.5),
    ("+1250.50", 1250.5),
])
def test_money_formats_preserve_scale(raw, expected):
    assert values.money(raw) == expected
    assert ingest.parse_money(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "NaN", "Infinity", float("inf"), float("nan"),
    True, False, -1, 0, "0.00", "-400,000", "(400000)",
    "4,00,000", "4.000.00", "400000,0000", "1234,567",
    "1e309", "1e6", "$", "not money", {}, [], 100_000_001,
])
def test_money_rejects_nonfinite_malformed_and_out_of_range(raw):
    assert values.money(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("5.84%", 5.84), ("5,84", 5.84), (0.0584, 5.84),
    ("0.25%", 0.25), ("0.15%", 0.15), ("0.05", 5),
    ("30%", 30), (5, 5), ("+4.99%", 4.99),
])
def test_percentage_units_are_explicit(raw, expected):
    assert values.percentage(raw) == expected


@pytest.mark.parametrize("raw", [True, {}, [], "NaN", "inf", "-1", "31%", "5%4", "5%%", "1e2", 0])
def test_bad_rates_are_not_guessed(raw):
    assert values.percentage(raw) is None


def test_canonical_fractional_percentage_survives_round_trip():
    imported = ingest.import_csv(
        b"Deal ID,Lender,Rate,Closing Date,Term,Current Balance,Rate Type,Amortization\n"
        b"D,TD,0.25%,2024-01-01,5,400000,Fixed,25\n"
    )["deals"][0]
    assert imported["contract_rate"] == 0.25
    assert ingest.deal_from_dict(imported).contract_rate == 0.25


def test_discount_is_percentage_points_not_a_fraction():
    assert ingest._parse_discount("0.25%") == 0.25
    assert ingest._parse_discount("0.025") == 0.025
    assert ingest._parse_discount(0) == 0
    assert ingest._parse_discount(True) is None


@pytest.mark.parametrize("raw,hint,amort,expected", [
    (6, "month", False, 6),
    (12, "month", False, 12),
    (5, "year", False, 60),
    ("5 years", "", False, 60),
    ("5y 6m", "", False, 66),
    ("18 months", "", False, 18),
    (25, "year", True, 300),
    (36, "month", True, 36),
    (36, "", True, 432),
    ("25 years 6 months", "", True, 306),
    ("6 mois", "", False, 6),
    ("5 ans", "", False, 60),
    ("0.5 years", "", False, 6),
])
def test_duration_units(raw, hint, amort, expected):
    assert values.duration(raw, hint, amortization=amort) == expected


@pytest.mark.parametrize("raw", [0, -5, float("inf"), float("nan"), "forever", "60 bananas", True, "1.5 months", 9999])
def test_duration_rejects_bad_values(raw):
    assert values.duration(raw, "month") is None


@pytest.mark.parametrize("raw,expected", [
    ("2024-02-29", date(2024, 2, 29)),
    ("2024/02/29", date(2024, 2, 29)),
    ("20240229", date(2024, 2, 29)),
    ("2024-02-29T22:30:00Z", date(2024, 2, 29)),
    (datetime(2024, 2, 29, 12), date(2024, 2, 29)),
    (date(2024, 2, 29), date(2024, 2, 29)),
    ("February 29, 2024", date(2024, 2, 29)),
    ("29 Feb 2024", date(2024, 2, 29)),
    ("45351", date(2024, 2, 29)),
])
def test_known_dates(raw, expected):
    assert values.read_date(raw).value == expected


def test_ambiguous_dates_require_a_choice():
    reading = values.read_date("03/04/2024")
    assert reading.value is None and reading.ambiguous
    assert values.read_date("03/04/2024", "day_first").value == date(2024, 4, 3)
    assert values.read_date("03/04/2024", "month_first").value == date(2024, 3, 4)
    assert values.read_date("04/04/2024").value == date(2024, 4, 4)


def test_explicit_date_order_never_falls_back_to_another_order():
    assert values.read_date("03/25/2024", "day_first").value is None
    assert values.read_date("25/03/2024", "month_first").value is None
    assert values.read_date("25/03/2024", "day_first").value == date(2024, 3, 25)
    assert values.read_date("03/25/2024", "month_first").value == date(2024, 3, 25)


@pytest.mark.parametrize("raw", ["2023-02-29", "2024-13-01", "2024-01-32", "12/40/2024", "1900-01-01", "2101-01-01", True, "NaN"])
def test_bad_calendar_dates(raw):
    assert values.read_date(raw).value is None


def test_date_detection_rejects_mixed_columns():
    assert values.infer_date_order(["25/03/2024", "01/04/2024"]) == ("day_first", False)
    assert values.infer_date_order(["03/25/2024"]) == ("month_first", False)
    assert values.infer_date_order(["03/04/2024"]) == (None, False)
    assert values.infer_date_order(["25/03/2024", "03/25/2024"]) == (None, True)


def test_ambiguous_csv_does_not_create_a_plausible_wrong_date():
    data = b"Deal ID,Lender,Rate,Closing Date,Term,Current Balance\nD,TD,5,03/04/2024,5,400000\n"
    first = ingest.import_csv(data)["deals"][0]
    assert first["closing_date"] is None
    assert any("ambiguous" in issue for issue in first["issues"])
    second = ingest.import_csv(data, date_order="day_first")["deals"][0]
    assert second["closing_date"] == "2024-04-03"
    third = ingest.import_csv(data, date_order="month_first")["deals"][0]
    assert third["closing_date"] == "2024-03-04"


def test_current_balance_wins_over_original_amount():
    result = ingest.import_csv(
        b"Deal ID,Mortgage Amount,Current Balance,Lender,Rate,Closing Date,Term\n"
        b"D,500000,420000,TD,5.5,2023-01-01,5\n"
    )
    assert result["mapping"]["balance"] == "Current Balance"
    assert result["deals"][0]["balance"] == 420000
    assert result["deals"][0]["balance_basis"] == "current"
    assert "Mortgage Amount" in result["ignored_columns"]


def test_french_amount_is_not_multiplied_by_one_hundred():
    result = ingest.import_csv(
        "Deal ID;Lender;Rate;Current Balance;Closing Date;Term\n"
        "D;TD;5,84;400000,50;2023-01-01;5\n"
    )
    assert result["deals"][0]["balance"] == 400000.5
    assert result["deals"][0]["contract_rate"] == 5.84


def test_explicit_original_balance_header_is_original():
    assert ingest._balance_basis("Original Principal Balance") == "original"
    assert ingest._balance_basis("Outstanding Balance") == "current"
    assert ingest._balance_basis("Mortgage Amount") == "original"


def test_json_source_layout_retains_units_and_booleans():
    imported = ingest.import_json(json.dumps([{
        "deal_id": "J", "lender": "TD", "contract_rate": 5.5,
        "closing_date": "2023-01-01", "term_months": 60,
        "balance": 400000, "amort_months": 36, "insured": False,
    }]))["deals"][0]
    assert imported["amort_months"] == 36
    assert imported["term_months"] == 60
    assert imported["insured"] is False


@pytest.mark.parametrize("raw,expected", [
    ("Bi-weekly", "biweekly"),
    ("Accelerated Biweekly", "accelerated_biweekly"),
    ("semi_monthly", "semi_monthly"),
    ("Weekly", "weekly"),
    ("monthly", "monthly"),
    ("fortnightly", "biweekly"),
    ("daily", None),
])
def test_payment_frequency_aliases(raw, expected):
    assert values.payment_frequency(raw) == expected


def test_rate_type_and_open_contract_are_separate():
    assert values.rate_kind("Closed") is None
    assert values.rate_kind("5 year Fixed Open") == "fixed"
    assert values.contract_is_open("5 year Fixed Open") is True
    assert values.contract_is_open("Fixed Closed") is False
    assert values.rate_kind("VRM") == "variable"


@pytest.mark.parametrize("text", ["=1+1", "+1", "-1+2", "@SUM(A1)", "\ttext", "  =1+1"])
def test_csv_formula_values_are_neutralized(text):
    assert values.csv_cell(text) == "'" + text


def test_csv_ordinary_values_remain_ordinary():
    assert values.csv_cell("F-1001") == "F-1001"
    assert values.csv_cell(123.45) == 123.45
    assert values.csv_cell(None) == ""
    assert values.csv_cell("Client A") == "Client A"


def test_rehydration_preserves_evidence_and_ocr_warning():
    source = {
        "deal_id": "O", "source": "ocr", "issues": ["read by OCR: verify every value"],
        "evidence": {"balance": {"page": 1, "excerpt": "Balance"}},
        "contract_rate": 5.5, "review_confirmed": False,
    }
    loaded = ingest.deal_from_dict(source)
    assert loaded.source == "ocr"
    assert loaded.evidence == source["evidence"]
    assert source["issues"][0] in loaded.issues
    assert loaded.review_confirmed is False


def test_unknown_rate_type_is_not_silently_fixed():
    loaded = ingest.deal_from_dict({"rate_type": "Unknown"})
    assert loaded.rate_type is None
    assert "invalid rate type" in loaded.issues
