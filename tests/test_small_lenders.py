"""Smaller lenders' own rate pages: one compact copy of each page's real structure, plus the not-public list."""
import json

from renewal.ratewatch import live, small_lenders as s

SERVUS = """<div class="catSection cat-1" data-catid="1"><h2>GICs</h2><div class="row rate"><span>1 Year</span><span>3.00%</span></div></div>
<div class="catSection cat-3 hidden" data-catid="3"><h2> Mortgages</h2><h4 class="effectiveDate">Effective: Thursday, October 15, 2026</h4>
<div class="productHeading">Fixed Rate Closed Mortgage</div>
<div class="row rate"><span>6 Month (Convertible)</span><span>5.49%   </span><span></span></div>
<div class="row rate"><span>5 Year (Conventional)&sup1;</span><span> 6.09% </span><span> 4.79% </span></div>
<div class="row rate"><span>5 Year (High Ratio)&sup1;</span><span>6.09%</span><span>4.69%</span></div>
<div class="productHeading">Fixed Rate Open Mortgage</div><div class="row rate"><span>5 Year</span><span>11.04%</span><span></span></div>
<div class="productHeading">Servus No Frills Mortgage</div><div class="row rate"><span>5 Year</span><span>6.09%</span><span>4.64%</span></div></div>"""

COMMUNITY = """<table><tr><td>Term (Closed)</td><td>1 Year</td><td>5 Years</td></tr>
<tr><td>Rate</td><td><span data-contrast="auto">5.24%</span></td><td><span data-contrast="auto">5.69%</span></td></tr></table>"""

CMLS = """<script>var MortgageRates={"Adjustable Rate Mortgage":[{"Term":"10","Rate":"4.45"},{"Term":"9","Rate":4.65}],
"Fixed Rate Mortgage":[{"Term":"1","Rate":"5.54"},{"Term":"5","Rate":"5.09"},{"Term":"16","Rate":"5.44"},{"Term":"11","Rate":"4.49"}]};</script>"""

RFA = """<p>Promotions</p><table><tr><td>5 Year Fixed QC (45-Day)</td><td>4.79%</td></tr></table><p>Standard Rates</p>
<table><tr><td>5 Year Fixed</td><td>4.89%</td><td>4.89%</td><td>5.04%</td></tr><tr><td>3 Year Fixed</td><td>4.84%</td></tr>
<tr><td>5 Year Fixed</td><td>5.29%</td></tr></table>"""

BRIDGEWATER = """<table><tr><th>Credit score</th><th>AIR/APR*</th><th>1-year term (%)</th><th>2-year term (%)</th><th>3-year term (%)</th><th>Max LTV</th></tr>
<tr><td>680+</td><td>AIR</td><td>5.04</td><td>5.24</td><td>5.49</td><td>80%</td></tr><tr><td></td><td>APR</td><td>6.15</td><td>5.85</td><td>5.93</td><td></td></tr>
<tr><td>640+</td><td>AIR</td><td>5.29</td><td>5.44</td><td>5.64</td><td>80%</td></tr></table>"""

HANA = """<script>var pbpuJsonObj01 = JSON.parse('{"rec":[{"irtLocalNm":"Can. Prime Rate","gBascIrt":"4.45000000","ctt":""}]}');
var pbpuJsonObj03 = JSON.parse('{"rec":[{"irtLocalNm":"Posted Rate","gBascIrt":"5.46000000","ctt":"1Year"},{"irtLocalNm":"Posted Rate","gBascIrt":"6.17000000","ctt":"5Year"}]}');</script>"""

ANTRIM = """<h3>Current Rates</h3><table id="tablepress-11"><tr><th></th><th>1st Mortgages</th><th>2nd Mortgages</th></tr>
<tr><td>50%</td><td>5.95% OPEN</td><td>8.95% OPEN</td></tr><tr><td>75%</td><td>6.95% OPEN</td><td>10.95% OPEN</td></tr>
<tr><td></td><td>Lender Fees: 1%</td><td>Lender Fees: 2%</td></tr></table>"""

ATRIUM = "<div><p>PURCHASES</p><p>1st</p><p>&le; 65%</p><p>6.49%</p><p>1.75%</p><p>CONDOS</p><p>Up to 75%</p><p>7.64%</p></div>"

HILLMOUNT = "<p>Our rates start at prime plus 2.50% for 1st mortgages and prime plus 3.50% for 2nd mortgages.</p>"


def test_servus_reads_only_the_mortgage_tab():
    rows = s.servus_rows(SERVUS)
    assert (60, "fixed_closed", "posted", 6.09) in rows and (60, "fixed_closed", "special", 4.79) in rows
    assert (60, "fixed_closed", "posted_insured", 6.09) in rows and (60, "open", "posted", 11.04) in rows
    assert not any(r[3] in (3.0, 4.64) for r in rows)        # GIC tab and No Frills product excluded


def test_community_trust_sideways_table():
    assert s.term_row_rows(COMMUNITY) == [(12, "fixed_closed", "posted", 5.24), (60, "fixed_closed", "posted", 5.69)]


def test_cmls_inline_json_with_option_codes():
    rows = s.cmls_rows(CMLS)
    assert (60, "fixed_closed", "special", 5.09) in rows and (60, "variable", "special", 4.65) in rows
    assert (60, "fixed_closed", "special_uninsured", 5.44) in rows
    assert not any(r[3] in (4.45, 4.49) for r in rows)        # prime and the Rate Advantage product are not terms


def test_rfa_standard_table_first_column_first_row():
    assert s.rfa_rows(RFA) == [(36, "fixed_closed", "special", 4.84), (60, "fixed_closed", "special", 4.89)]


def test_bridgewater_best_credit_tier_air_row():
    assert s.bridgewater_rows(BRIDGEWATER) == [(12, "fixed_closed", "special", 5.04), (24, "fixed_closed", "special", 5.24),
                                               (36, "fixed_closed", "special", 5.49)]


def test_hana_posted_rates_from_inline_json():
    assert s.hana_rows(HANA) == [(12, "fixed_closed", "posted", 5.46), (60, "fixed_closed", "posted", 6.17)]


def test_bloom_reverse_mortgage_feed():
    rows = s.bloom_rows(json.dumps({"fiveYearRate": 6.33, "fiveYearResetRate": 6.33, "oneYearResetRate": 6.94}))
    assert (60, "fixed_closed", "special", 6.33) in rows and (12, "fixed_closed", "special", 6.94) in rows


def test_private_lenders_one_year_rates():
    assert s.antrim_rows(ANTRIM) == [(12, "open", "special", 5.95)]
    assert s.atrium_rows(ATRIUM) == [(12, "fixed_closed", "special", 6.49)]
    assert s.hillmount_rows(HILLMOUNT, prime=4.45) == [(12, "fixed_closed", "special", 6.95)]


def test_short_term_private_lender_validates_on_its_longest_term():
    anchor = {"goc_5y": 3.53, "boc_5y_posted": 6.19}
    assert live.validate([(12, "open", "special", 5.95)], "alternative", anchor)[0]
    assert not live.validate([(12, "fixed_closed", "special", 5.95)], "credit_union", anchor)[0]   # CUs still need 5-yr


def test_not_public_lenders_are_never_fetched(monkeypatch):
    called = []
    monkeypatch.setattr(live, "read_live", lambda *a: called.append(a) or [])
    home_trust = next(l for l in live.LENDERS if l[0] == "ALT01")
    row = live.resolve(home_trust, {"goc_5y": 3.5, "boc_5y_posted": 6.19})
    assert row["tier"] == "not_public" and called == [] and "bot protection" in row["tried"][0]["reason"]
    assert not any(l[0] in ("ALT13", "ALT26") for l in live.LENDERS)       # commercial-only lenders removed
