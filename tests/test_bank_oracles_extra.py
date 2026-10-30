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
