"""Equitable Bank backup source parser and its registration on the live board."""
from renewal.ratewatch import live, scrape

PAGE = """<table><tr><th>Mortgage</th><th>6 Month 2</th><th>1 Year Fixed</th><th>2 Year Fixed</th><th>3 Year Fixed</th>
<th>4 Year Fixed</th><th>5 Year Fixed</th><th>5 Year Adjustable</th></tr>
<tr><td>Standard Mortgage Rate (Closed)</td><td>--</td><td>5.29%</td><td>5.39%</td><td>5.49%</td><td>6.44%</td><td>5.59%</td><td></td></tr></table>
<table><tr><td>Reverse Mortgage Flex</td><td>6 Month Fixed</td><td>7.98%</td><td>9.634%</td></tr></table>"""


def test_equitable_reads_only_the_standard_posted_table():
    rows = scrape.equitable_rows(PAGE)
    assert (60, "fixed_closed", "posted", 5.59) in rows and (12, "fixed_closed", "posted", 5.29) in rows
    assert all(r[3] < 7 for r in rows)                     # reverse-mortgage rates and APRs are not picked up


def test_equitable_is_backup_source_for_eq_bank():
    row = next(r for r in live.LENDERS if r[0] == "ALT02")
    assert row[4] == ("equitable", "https://www.equitablebank.ca/mortgage-rates")
    assert live.parse_text("equitable", PAGE) == scrape.equitable_rows(PAGE)


def test_bmo_flat_rates_file_reads_posted_fixed_terms_only():
    from renewal.ratewatch import backfill
    text = '{"CMS": {}, "fixed-5-year-closed": "5.34", "fixed-5-year-closed-special": "3.54", "fixed-7-year-closed-apr": "3.6"}'
    assert backfill.parse("bmo_flat", text) == [(60, "fixed_closed", "posted", 5.34)]


def test_arquivo_is_an_extra_archive_pass():
    from renewal.ratewatch import backfill, history
    assert callable(backfill.arquivo_pass) and history.HOW_PRIORITY["arquivo"] == 3


def test_gap_fills_are_labelled_and_never_used_as_current_rates(tmp_path, monkeypatch):
    from datetime import date
    from renewal.ratewatch import history
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db", raising=False)
    history.save("P023", "2026-10-14", [(60, "fixed_closed", "posted", 6.09)], "boc_typical")
    assert history.table_on("P023", date(2026, 10, 15))[0] == {60: 6.09}
    assert history.provenance("P023", date(2026, 10, 15)) == "boc_typical"
    assert history.table_on("P023", date(2026, 10, 15), own_only=True)[0] == {}
    history.save("P023", "2026-10-15", [(60, "fixed_closed", "posted", 6.19)], "api")
    assert history.table_on("P023", date(2026, 10, 15), own_only=True)[0] == {60: 6.19}


def test_fill_gaps_bridges_only_identical_readings_with_flat_boc(tmp_path, monkeypatch):
    import json
    from renewal.ratewatch import backfill, history
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db", raising=False)
    monkeypatch.setattr(backfill, "FILLS", tmp_path / "fills.json")
    monkeypatch.setattr(backfill, "COVERAGE", tmp_path / "cov.json")
    monkeypatch.setattr(backfill, "SOURCES", {"P025": []})
    monkeypatch.setattr(backfill, "months", lambda: ["202401", "202402", "202403", "202404"])
    for d, v in (("2024-01-10", 6.79), ("2024-02-14", 6.79), ("2024-03-13", 6.79), ("2024-04-10", 6.59)):
        history.save("BIG6_TYPICAL", d, [(t, "fixed_closed", "posted", v) for t in (12, 36, 60)], "boc")
    history.save("P025", "2024-01-10", [(60, "fixed_closed", "posted", 6.79), (24, "fixed_closed", "posted", 6.5)], "arquivo")
    history.save("P025", "2024-03-13", [(60, "fixed_closed", "posted", 6.79)], "arquivo")
    prog = {"P025": {"202401": {"how": "arquivo/scotia_json", "ts": "20240110", "rate5": 6.79, "boc": 6.79},
                     "202403": {"how": "arquivo/scotia_json", "ts": "20240313", "rate5": 6.79, "boc": 6.79}}}
    fills = backfill.fill_gaps(prog)["P025"]
    assert fills["202402"]["how"] == "bridged"                       # same bank rate both sides, BoC flat between
    assert fills["202404"]["how"] == "boc_typical"                   # nothing after: official fallback, labelled
    assert "202401" not in fills and "202403" not in fills           # bank-own months untouched
    assert json.loads((tmp_path / "fills.json").read_text())["P025"]["202402"]["from"] == ["202401", "202403"]


def test_refill_drops_a_fill_once_bank_own_data_arrives(tmp_path, monkeypatch):
    from datetime import date
    from renewal.ratewatch import backfill, history
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db", raising=False)
    monkeypatch.setattr(backfill, "FILLS", tmp_path / "fills.json")
    monkeypatch.setattr(backfill, "COVERAGE", tmp_path / "cov.json")
    monkeypatch.setattr(backfill, "SOURCES", {"P023": []})
    monkeypatch.setattr(backfill, "months", lambda: ["202410"])
    history.save("BIG6_TYPICAL", "2024-10-30", [(t, "fixed_closed", "posted", 6.49) for t in (12, 36, 60)], "boc")
    backfill.fill_gaps({})
    assert history.provenance("P023", date(2024, 10, 31)) == "boc_typical"
    history.save("P023", "2024-10-05", [(60, "fixed_closed", "posted", 6.59)], "arquivo")
    backfill.fill_gaps({"P023": {"202410": {"how": "arquivo/html", "ts": "20241005", "rate5": 6.59, "boc": 6.49}}})
    assert history.table_on("P023", date(2024, 10, 31))[0] == {60: 6.59}
