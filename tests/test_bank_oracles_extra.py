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


def test_bmo_rate_include_parser():
    from renewal.ratewatch import backfill
    js = ("var MORTGAGE = {'fixed' : {'6 month \x28convertible\x29' : {'frn_name':'x', 'value':'3.040', 'product_code':'a', "
          "'type':'convertible', 'term_months':'6'},\n'6 month \x28open\x29' : {'frn_name':'x', 'value':'5.950', 'product_code':'b', "
          "'type':'open', 'term_months':'6'},\n'5 year \x28closed\x29' : {'frn_name':'x', 'value':'4.790', 'product_code':'c', "
          "'type':'closed', 'term_months':'60'}}, 'variable' : {'5 year' : {'value':'2.000', 'type':'closed', 'term_months':'60'}}};")
    rows = backfill.parse("bmo_include", js)
    assert (60, "fixed_closed", "posted", 4.79) in rows and (6, "fixed_closed", "posted", 3.04) in rows
    assert (6, "open", "posted", 5.95) in rows and not any(r[3] == 2.0 for r in rows)    # variable block ignored


def test_gzip_archived_bodies_are_unpacked():
    import gzip
    from renewal.ratewatch import backfill

    class R:
        content = gzip.compress(b"<table><tr><td>5 year fixed</td><td>7.14%</td></tr></table>")
        text = "\x1f\x8bgarbage"
    assert "7.14%" in backfill.body_text(R())


def test_warc_body_unpacks_gzip_and_chunked():
    import gzip
    from renewal.ratewatch import backfill
    page = b"<td>5 year fixed</td><td>7.14%</td>"
    z = gzip.compress(page)
    rec = b"WARC/1.0\r\nWARC-Type: response\r\n\r\nHTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + z
    assert "7.14%" in backfill.warc_body(rec)
    chunked = b"WARC/1.0\r\n\r\nHTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + \
        f"{len(page):x}".encode() + b"\r\n" + page + b"\r\n0\r\n\r\n"
    assert backfill.warc_body(chunked) == page.decode()


def test_bmo_has_its_rate_include_as_backup_source():
    from renewal.ratewatch import live
    row = next(r for r in live.LENDERS if r[0] == "P027")
    assert row[4] == ("bmo_include", "https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp")
    js = "var MORTGAGE = {'fixed' : {'5 year (closed)' : {'value':'6.090', 'type':'closed', 'term_months':'60'}}};"
    assert live.parse_text("bmo_include", js) == [(60, "fixed_closed", "posted", 6.09)]


def test_deposit_rates_are_never_read_as_mortgage_rates():
    from renewal.ratewatch.parse import extract_rates
    html = ("<h3>Non-Redeemable GICs</h3><table><tr><td>1 Year</td><td>3.00%</td></tr><tr><td>5 Year</td><td>3.35%</td></tr></table>"
            "<div>Long Term GIC - Annual Interest 1 Year 3.00% 2 Year 3.00%</div>")
    assert extract_rates(html) == []
    html += "<h3>Mortgage rates</h3><table><tr><td>5 Year Fixed</td><td>4.59%</td></tr></table>"
    assert any(r[0] == 60 and r[3] == 4.59 for r in extract_rates(html))


def test_duca_posted_rate_pdf_parser(monkeypatch):
    from renewal.ratewatch import scrape
    import pypdf

    class Page:
        def extract_text(self):
            return ("DUCA Posted Mortgage Rates-Effective September 18, 2026\nTerm 1 Year Fixed 2 Year Fixed 3 Year Fixed "
                    "4 Year Fixed 5 Year Fixed\nPosted Rate1 5.34% 5.24% 4.69% 4.89% 4.59%")
    monkeypatch.setattr(pypdf, "PdfReader", lambda f: type("R", (), {"pages": [Page()]})())
    assert scrape.duca_pdf_rows(b"%PDF") == [(12, "fixed_closed", "posted", 5.34), (24, "fixed_closed", "posted", 5.24),
                                            (36, "fixed_closed", "posted", 4.69), (48, "fixed_closed", "posted", 4.89),
                                            (60, "fixed_closed", "posted", 4.59)]


COAST_PAGE = """<h3>Featured Mortgage Rates</h3><table><tr><td>5-Year Fixed</td><td>4.84% 5</td><td>4.86% 2</td></tr></table>
<h3>Fixed Rate Mortgages</h3><table><tr><th>Mortgage Terms Rate effective 13-Oct-26</th><th>Up to 25</th><th>APR</th></tr>
<tr><td>1-Year Fixed Rate - Open</td><td>6.39% 5</td><td>6.49% 2</td></tr>
<tr><td>1-Year Fixed Rate</td><td>4.89% 5</td><td>4.99% 2</td></tr>
<tr><td>5-Year Fixed Rate</td><td>4.84% 5</td><td>4.86% 2</td></tr>
<tr><td>5-Year Fixed High Ratio</td><td>4.49% 3</td><td>4.51% 2</td></tr></table>
<h3>Posted rates - Fixed Rate Mortgages</h3><table><tr><th>Mortgage Terms Rate effective 30-Jun-26</th><th>Rate</th><th>APR</th></tr>
<tr><td>1-Year Fixed Rate - Closed</td><td>5.50% 1</td><td>5.60% 2</td></tr>
<tr><td>5-Year Fixed Rate - Closed</td><td>6.10% 1</td><td>6.12% 2</td></tr>
<tr><td>10-Year Fixed Rate - Closed</td><td>6.80% 1</td><td>6.81% 2</td></tr></table>
<h3>Posted rates - Variable Rate Mortgages</h3><table><tr><td>5-Year Variable Rate - Closed</td><td>4.45% 2</td></tr></table>"""


def test_coast_capital_tables_are_labelled_by_their_headings():
    from renewal.ratewatch import live, scrape
    rows = scrape.coast_rows(COAST_PAGE)
    assert (60, "fixed_closed", "posted", 6.10) in rows and (120, "fixed_closed", "posted", 6.80) in rows
    assert (60, "fixed_closed", "special", 4.84) in rows and (12, "fixed_closed", "special", 4.89) in rows
    assert not any(r[3] in (6.39, 4.49, 4.45, 4.86, 6.12) for r in rows)     # open, high-ratio, variable, APR excluded
    row = next(r for r in live.LENDERS if r[0] == "CU03")
    assert row[3] == ("coast", "https://www.coastcapitalsavings.com/rates/mortgages")
