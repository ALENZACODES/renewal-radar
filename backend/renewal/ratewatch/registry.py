"""Source registry: 100 primary scrape targets + 100 back-check targets.

Edit URLs here, then run `python -m renewal.ratewatch.build_registry` to regenerate the CSVs.
Fields
  method:     api_json | api_csv | zip_csv | html | html_js (needs browser) | pdf | archive
  ird_method: posted_discount | offered_rate | n/a      (best-known default; VERIFY per lender's charge terms)
  fix_from:   where to look first when the source breaks
"""

VALET = "https://www.bankofcanada.ca/valet/observations"
STC = "https://www150.statcan.gc.ca"

# id, name, category, data, url, method, ird_method, fix_from
PRIMARY = [
    # ---------------- Official / government (free, keyless APIs) ----------------
    ("P001", "Bank of Canada - big-6 posted mortgage rates 1/3/5yr + prime", "official", "posted_rates", f"{VALET}/group/CHARTERED_BANK_INTEREST/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P002", "Bank of Canada - actual rates on NEW mortgages (insured/uninsured by term)", "official", "effective_rates", f"{VALET}/group/A4_RATES_MORTGAGES/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P003", "Bank of Canada - GoC benchmark bond yields 2/3/5/7/10yr", "official", "bond_yields", f"{VALET}/group/bond_yields_benchmark/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P004", "Bank of Canada - marketable bond average yields", "official", "bond_yields", f"{VALET}/group/bond_yields_marketable/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P005", "Bank of Canada - policy rate (target overnight)", "official", "policy_rate", f"{VALET}/V39079/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/series/json"),
    ("P006", "Bank of Canada - CORRA", "official", "policy_rate", f"{VALET}/AVG.INTWO/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/series/json"),
    ("P007", "Bank of Canada - Canada Mortgage Bond purchases", "official", "cmb_yields", f"{VALET}/group/CANADA_MORTGAGE_BOND/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P008", "Bank of Canada - mortgage origination characteristics", "official", "market_stats", f"{VALET}/group/FVI_CHARACTERISTICS_MORTGAGE_ORIGINATIONS/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P009", "Bank of Canada - funds advanced, mortgages", "official", "market_stats", f"{VALET}/group/A4_FUNDS_MORTGAGES/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P010", "Bank of Canada - senior loan officer survey (mortgage)", "official", "market_stats", f"{VALET}/group/slos_mortgage_lending/json", "api_json", "n/a", "https://www.bankofcanada.ca/valet/lists/groups/json"),
    ("P011", "StatCan table 10-10-0145 (posted rates, full history CSV)", "official", "posted_rates", f"{STC}/n1/tbl/csv/10100145-eng.zip", "zip_csv", "n/a", f"{STC}/t1/tbl1/en/tv.action?pid=1010014501"),
    ("P012", "StatCan table 34-10-0145 CMHC conventional 5yr rate", "official", "posted_rates", f"{STC}/n1/tbl/csv/34100145-eng.zip", "zip_csv", "n/a", f"{STC}/t1/tbl1/en/tv.action?pid=3410014501"),
    ("P013", "StatCan table 10-10-0122 financial market statistics", "official", "bond_yields", f"{STC}/n1/tbl/csv/10100122-eng.zip", "zip_csv", "n/a", f"{STC}/t1/tbl1/en/tv.action?pid=1010012201"),
    ("P014", "StatCan table 18-10-0205 New Housing Price Index", "official", "market_stats", f"{STC}/n1/tbl/csv/18100205-eng.zip", "zip_csv", "n/a", f"{STC}/t1/tbl1/en/tv.action?pid=1810020501"),
    ("P015", "StatCan WDS cube list (find any table id)", "official", "catalogue", f"{STC}/t1/wds/rest/getAllCubesListLite", "api_json", "n/a", "https://www.statcan.gc.ca/en/developers/wds/user-guide"),
    ("P016", "CMHC Housing Market Information Portal", "official", "market_stats", "https://www03.cmhc-schl.gc.ca/hmip-pimh/en", "html_js", "n/a", "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research"),
    ("P017", "Open Government Canada CKAN search (mortgage)", "official", "catalogue", "https://open.canada.ca/data/api/3/action/package_search?q=mortgage", "api_json", "n/a", "https://open.canada.ca/en/access-our-application-programming-interface-api"),
    ("P018", "CBA residential mortgages in arrears", "official", "market_stats", "https://cba.ca/article/mortgages-in-arrears", "html", "n/a", "https://cba.ca/"),
    ("P019", "CREA national MLS statistics", "official", "market_stats", "https://stats.crea.ca/en-ca/", "html_js", "n/a", "https://www.crea.ca/housing-market-stats/"),
    ("P020", "Teranet-National Bank House Price Index", "official", "market_stats", "https://housepriceindex.ca/", "html", "n/a", "https://housepriceindex.ca/"),
    # ---------------- Big 6 banks: current + historical posted rates ----------------
    ("P021", "RBC mortgage rates", "big6", "posted+special", "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html", "html", "posted_discount", "https://www.rbcroyalbank.com/sitemap.xml"),
    ("P022", "RBC prime rate", "big6", "prime", "https://www.rbcroyalbank.com/rates/prime.html", "html", "n/a", "https://www.rbcroyalbank.com/rates/"),
    ("P023", "TD mortgage rates (hidden API psservice getRates = posted+discount+special)", "big6", "posted+special", "https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates", "api_json", "posted_discount", "https://www.td.com/sitemap.xml"),
    ("P024", "TD prime rate", "big6", "prime", "https://www.td.com/ca/en/personal-banking/products/todays-rates-and-prime", "html", "n/a", "https://www.td.com/sitemap.xml"),
    ("P025", "Scotiabank mortgage rates", "big6", "posted+special", "https://www.scotiabank.com/ca/en/personal/rates-prices/mortgages-rates.html", "html_js", "posted_discount", "https://www.scotiabank.com/sitemap.xml"),
    ("P026", "Scotiabank prepayment charge rules (policy tracking)", "big6", "historical_posted", "https://www.scotiabank.com/ca/en/personal/mortgages/understanding-mortgage-prepayments-charges.html", "html", "posted_discount", "https://www.scotiabank.com/sitemap.xml"),
    ("P027", "BMO mortgage rates (blocks scripts - browser mode)", "big6", "posted+special", "https://www.bmo.com/main/personal/mortgages/mortgage-rates/", "html_js", "posted_discount", "https://www.bmo.com/sitemap.xml"),
    ("P028", "BMO posted-rate history via Wayback (BMO blocks scripts)", "big6", "historical_posted", "https://web.archive.org/cdx/search/cdx?url=bmo.com/main/personal/mortgages/mortgage-rates/&output=json&limit=5", "archive", "posted_discount", "https://www.bmo.com/sitemap.xml"),
    ("P029", "CIBC mortgage rates (hidden API cibconline productRatesLegacy)", "big6", "posted+special", "https://www.cibc.com/en/interest-rates/mortgage-rates.html", "api_json", "posted_discount", "https://www.cibc.com/sitemap.xml"),
    ("P030", "CIBC prepayment charge rules (policy tracking)", "big6", "historical_posted", "https://www.cibc.com/en/personal-banking/mortgages/resource-centre/prepayment.html", "html", "posted_discount", "https://www.cibc.com/sitemap.xml"),
    ("P031", "National Bank mortgage rates", "big6", "posted+special", "https://www.nbc.ca/personal/mortgages/rates.html", "html", "posted_discount", "https://www.nbc.ca/sitemap.xml"),
    ("P032", "National Bank Optimum (broker channel) rates", "big6", "historical_posted", "https://www.nbc.ca/en/optimummortgage/brokers/rates.html", "html", "posted_discount", "https://www.nbc.ca/sitemap.xml"),
    # ---------------- Other banks / direct banks ----------------
    ("P033", "Tangerine mortgage rates", "bank", "posted+special", "https://www.tangerine.ca/en/rates/mortgage-rates", "html_js", "posted_discount", "https://www.tangerine.ca/sitemap.xml"),
    ("P034", "Simplii Financial mortgage rates", "bank", "posted+special", "https://www.simplii.com/en/rates/mortgage-rates.html", "html_js", "posted_discount", "https://www.simplii.com/sitemap.xml"),
    ("P035", "Desjardins mortgage rates", "bank", "posted+special", "https://www.desjardins.com/en/mortgage/mortgage-rates.html", "html", "posted_discount", "https://www.desjardins.com/sitemap.xml"),
    ("P036", "Laurentian Bank mortgage rates", "bank", "posted", "https://www.laurentianbank.ca/en/personal/rates/mortgages", "html_js", "posted_discount", "https://www.laurentianbank.ca/sitemap.xml"),
    ("P037", "B2B Bank mortgage rates", "bank", "posted", "https://b2bbank.com/mybank/rates/index", "html", "posted_discount", "https://www.b2bbank.com/sitemap.xml"),
    ("P038", "Manulife Bank mortgage rates", "bank", "posted", "https://www.manulifebank.ca/personal-banking/rates.html", "html", "posted_discount", "https://www.manulifebank.ca/sitemap.xml"),
    ("P039", "ATB Financial mortgage rates", "bank", "posted+special", "https://www.atb.com/resources/rates/mortgage-rates/", "html", "posted_discount", "https://www.atb.com/sitemap.xml"),
    ("P040", "EQ Bank / Equitable Bank mortgage rates", "bank", "offered", "https://www.eqbank.ca/personal-banking/mortgages", "html_js", "offered_rate", "https://www.eqbank.ca/sitemap.xml"),
    ("P041", "Home Trust mortgage rates", "trust", "offered", "https://www.hometrust.ca/rates/", "html", "offered_rate", "https://www.hometrust.ca/sitemap.xml"),
    ("P042", "Haventree Bank", "bank", "offered", "https://www.haventreebank.com/en-CA", "html", "offered_rate", "https://www.haventreebank.com/sitemap.xml"),
    ("P043", "Bridgewater Bank", "bank", "offered", "https://bridgewaterbank.ca/", "html", "offered_rate", "https://www.bridgewaterbank.ca/sitemap.xml"),
    ("P044", "Peoples Group (formerly Peoples Trust)", "trust", "offered", "https://www.peoplesgroup.com/", "html", "offered_rate", "https://www.peoplestrust.com/sitemap.xml"),
    ("P045", "Community Trust", "trust", "offered", "https://www.communitytrust.ca/", "html", "offered_rate", "https://www.communitytrust.ca/sitemap.xml"),
    ("P046", "Equitable Bank (residential + reverse)", "bank", "offered", "https://www.equitablebank.ca/", "html", "offered_rate", "https://www.cffbank.ca/sitemap.xml"),
    ("P047", "Wealth One Bank of Canada", "bank", "offered", "https://www.wealthonebankofcanada.com/", "html", "offered_rate", "https://www.wealthonebankofcanada.com/sitemap.xml"),
    ("P048", "ICICI Bank Canada mortgage rates", "bank", "posted", "https://www.icicibank.ca/personal-banking", "html", "posted_discount", "https://www.icicibank.ca/sitemap.xml"),
    ("P049", "HomeEquity Bank (CHIP reverse mortgage)", "bank", "offered", "https://www.chip.ca/current-rates/", "html", "offered_rate", "https://www.chip.ca/sitemap.xml"),
    ("P050", "Concentra Bank (Wyth Financial)", "trust", "offered", "https://concentra.ca/", "html", "offered_rate", "https://www.wyth.ca/sitemap.xml"),
    # ---------------- Monoline / broker-channel lenders ----------------
    ("P051", "MCAP", "monoline", "offered", "https://www.mcap.com/", "html", "offered_rate", "https://www.mcap.com/sitemap.xml"),
    ("P052", "First National Financial", "monoline", "offered", "https://www.firstnational.ca/", "html", "offered_rate", "https://www.firstnational.ca/sitemap.xml"),
    ("P053", "RMG Mortgages", "monoline", "offered", "https://www.rmgmortgages.ca/", "html", "offered_rate", "https://www.rmgmortgages.ca/sitemap.xml"),
    ("P054", "CMLS Financial", "monoline", "offered", "https://www.cmls.ca/", "html", "offered_rate", "https://www.cmls.ca/sitemap.xml"),
    ("P055", "Merix Financial", "monoline", "offered", "https://www.merixfinancial.com/", "html", "offered_rate", "https://www.merixfinancial.com/sitemap.xml"),
    ("P056", "Lendwise", "monoline", "offered", "https://lendwise.com/", "html", "offered_rate", "https://www.lendwise.com/sitemap.xml"),
    ("P057", "Fisgard Capital (private/MIC)", "monoline", "offered", "https://www.fisgard.com/", "html", "offered_rate", "https://www.strivemortgage.ca/sitemap.xml"),
    ("P058", "Marathon Mortgage", "monoline", "offered", "https://marathonmortgage.ca/", "html", "offered_rate", "https://www.marathonmortgage.ca/sitemap.xml"),
    ("P059", "Antrim Investments (private/MIC)", "monoline", "offered", "https://www.antriminvestments.com/", "html", "offered_rate", "https://www.bloomfinance.ca/sitemap.xml"),
    ("P060", "Cameron Stephens (alt-A)", "trust", "offered", "https://cameronstephens.com/", "html", "offered_rate", "https://www.cameronstephens.com/sitemap.xml"),
    # ---------------- Online / broker-direct (best discounted market rate) ----------------
    ("P061", "nesto mortgage rates", "online", "discounted", "https://www.nesto.ca/mortgage-rates/", "html", "n/a", "https://www.nesto.ca/sitemap.xml"),
    ("P062", "True North Mortgage rates", "online", "discounted", "https://www.truenorthmortgage.ca/rates", "html", "n/a", "https://www.truenorthmortgage.ca/sitemap.xml"),
    ("P063", "WFCU Credit Union (Windsor ON)", "credit_union", "posted+special", "https://www.wfcu.ca/", "html", "offered_rate", "https://www.wfcu.ca/sitemap.xml"),
    ("P064", "Pine mortgage rates", "online", "discounted", "https://www.pine.ca/", "html_js", "n/a", "https://pine.ca/sitemap.xml"),
    ("P065", "Neo Financial mortgages", "online", "discounted", "https://www.neofinancial.com/mortgages", "html_js", "n/a", "https://www.neofinancial.com/sitemap.xml"),
    ("P066", "Clover Mortgage (homewise.ca now redirects to a plumber)", "online", "discounted", "https://www.clovermortgage.ca/", "html_js", "n/a", "https://www.homewise.ca/sitemap.xml"),
    ("P067", "Perch", "online", "discounted", "https://myperch.io/", "html_js", "n/a", "https://www.myperch.io/sitemap.xml"),
    ("P068", "CanWise", "online", "discounted", "https://www.canwise.com/", "html", "n/a", "https://canwise.com/sitemap.xml"),
    ("P069", "Intelli Mortgage", "online", "discounted", "https://www.intellimortgage.com/", "html", "n/a", "https://www.intellimortgage.com/sitemap.xml"),
    ("P070", "Breezeful", "online", "discounted", "https://breezeful.com/", "html_js", "n/a", "https://www.breezeful.com/sitemap.xml"),
    # ---------------- Credit unions ----------------
    ("P071", "Vancity", "credit_union", "posted+special", "https://www.vancity.com/rates/", "html", "offered_rate", "https://www.vancity.com/sitemap.xml"),
    ("P072", "Coast Capital Savings", "credit_union", "posted+special", "https://www.coastcapitalsavings.com/rates", "html_js", "offered_rate", "https://www.coastcapitalsavings.com/sitemap.xml"),
    ("P073", "Meridian Credit Union", "credit_union", "posted+special", "https://www.meridiancu.ca/personal/rates-and-fees/mortgage-and-borrowing-rates", "html", "offered_rate", "https://www.meridiancu.ca/sitemap.xml"),
    ("P074", "Servus Credit Union", "credit_union", "posted+special", "https://servus.ca/rates", "html", "offered_rate", "https://servus.ca/sitemap.xml"),
    ("P075", "Alterna Savings", "credit_union", "posted+special", "https://www.alterna.ca/en/rates/mortgages", "html", "offered_rate", "https://www.alterna.ca/sitemap.xml"),
    ("P076", "DUCA", "credit_union", "posted+special", "https://www.duca.com/rates", "html", "offered_rate", "https://www.duca.com/sitemap.xml"),
    ("P077", "FirstOntario Credit Union", "credit_union", "posted+special", "https://www.firstontario.com/personal/rates/", "html", "offered_rate", "https://www.firstontario.com/sitemap.xml"),
    ("P078", "Libro Credit Union", "credit_union", "posted+special", "https://www.libro.ca/rates-fees/", "html", "offered_rate", "https://www.libro.ca/sitemap.xml"),
    ("P079", "Affinity Credit Union", "credit_union", "posted+special", "https://www.affinitycu.ca/rates/overview", "html", "offered_rate", "https://www.affinitycu.ca/sitemap.xml"),
    ("P080", "Conexus Credit Union", "credit_union", "posted+special", "https://www.conexus.ca/rates", "html", "offered_rate", "https://www.conexus.ca/sitemap.xml"),
    ("P081", "Steinbach Credit Union", "credit_union", "posted+special", "https://scu.mb.ca/rates", "html", "offered_rate", "https://www.scu.mb.ca/sitemap.xml"),
    ("P082", "Cambrian Credit Union", "credit_union", "posted+special", "https://www.cambrian.mb.ca/rates", "html", "offered_rate", "https://www.cambrian.mb.ca/sitemap.xml"),
    ("P083", "TRU Cooperative Bank (formerly First West / Envision / Valley First)", "credit_union", "posted+special", "https://www.trucooperativebank.ca/", "html", "offered_rate", "https://www.firstwestcu.ca/sitemap.xml"),
    ("P084", "beem credit union (BlueShore + Gulf & Fraser + Interior Savings)", "credit_union", "posted+special", "https://beemcreditunion.ca/personalrates", "html", "offered_rate", "https://www.blueshorefinancial.com/sitemap.xml"),
    ("P085", "Coastal Community Credit Union", "credit_union", "posted+special", "https://www.cccu.ca/", "html", "offered_rate", "https://www.gulfandfraser.com/sitemap.xml"),
    ("P086", "Synergy Credit Union", "credit_union", "posted+special", "https://www.synergycu.ca/", "html", "offered_rate", "https://www.interiorsavings.com/sitemap.xml"),
    ("P087", "Access Credit Union (absorbed Sunova)", "credit_union", "posted+special", "https://www.accesscu.ca/en/rates", "html", "offered_rate", "https://www.prospera.ca/sitemap.xml"),
    ("P088", "Kawartha Credit Union", "credit_union", "posted+special", "https://www.kawarthacu.com/rates", "html", "offered_rate", "https://www.kawarthacu.com/sitemap.xml"),
    ("P089", "Tandia Financial", "credit_union", "posted+special", "https://www.tandia.com/rates", "html", "offered_rate", "https://www.tandia.com/sitemap.xml"),
    ("P090", "Your Neighbourhood Credit Union", "credit_union", "posted+special", "https://www.yncu.com/resources/rates/mortgage-rates", "html", "offered_rate", "https://www.yncu.com/sitemap.xml"),
    ("P091", "UNI Financial Cooperation (NB)", "credit_union", "posted+special", "https://www.uni.ca/en/rates", "html", "offered_rate", "https://www.uni.ca/sitemap.xml"),
    ("P092", "Copperfin Credit Union (ON; Connect First merged into Servus)", "credit_union", "posted+special", "https://www.copperfin.ca/", "html", "offered_rate", "https://www.copperfin.ca/sitemap.xml"),
    ("P093", "Kindred Credit Union", "credit_union", "posted+special", "https://www.kindredcu.com/", "html", "offered_rate", "https://www.sunovacu.ca/sitemap.xml"),
    ("P094", "Innovation Credit Union", "credit_union", "posted+special", "https://www.innovationcu.ca/personal/borrowing/mortgage-rates.html", "html", "offered_rate", "https://www.innovationcu.ca/sitemap.xml"),
    ("P095", "Mainstreet Credit Union", "credit_union", "posted+special", "https://mainstreetcu.ca/rates", "html", "offered_rate", "https://www.mainstreetcu.ca/sitemap.xml"),
    # ---------------- Consumer credit / home-equity lenders ----------------
    ("P096", "Fairstone (home equity; rates only in application)", "credit_co", "offered", "https://www.fairstone.ca/en/", "html", "n/a", "https://www.fairstone.ca/sitemap.xml"),
    ("P097", "easyfinancial home equity", "credit_co", "offered", "https://www.easyfinancial.com/home-equity-loans", "html", "n/a", "https://www.easyfinancial.com/sitemap.xml"),
    ("P098", "Spring Financial mortgages", "credit_co", "offered", "https://springfinancial.ca/mortgages/", "html", "n/a", "https://www.springfinancial.ca/sitemap.xml"),
    # ---------------- History engines (the posted rate AT ORIGINATION for IRD) ----------------
    ("P099", "Wayback Machine CDX API (snapshots of any bank rate page)", "archive", "historical_posted", "https://web.archive.org/cdx/search/cdx?url=rbcroyalbank.com/mortgages/mortgage-rates.html&output=json&limit=5", "archive", "n/a", "https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server"),
    ("P100", "Common Crawl index (alternate copies of bank rate pages)", "archive", "historical_posted", "https://index.commoncrawl.org/collinfo.json", "archive", "n/a", "https://commoncrawl.org/get-started"),
]

# id, name, validates, url, method, rule, fix_from
CHECKS = [
    # ---------------- Official cross-checks (independent systems, same numbers) ----------------
    ("C001", "StatCan WDS vector 80691335 (same number as BoC V80691335)", "P001", f"{STC}/t1/wds/rest/getDataFromVectorsAndLatestNPeriods", "api_json", "StatCan value == BoC value for same week", "https://www.statcan.gc.ca/en/developers/wds/user-guide"),
    ("C002", "BoC Valet CSV endpoint (format-independent re-read)", "P001", f"{VALET}/V80691335/csv", "api_csv", "CSV == JSON", "https://www.bankofcanada.ca/valet/docs"),
    ("C003", "BoC posted interest rates page (human-readable)", "P001", "https://www.bankofcanada.ca/rates/banking-and-financial-statistics/posted-interest-rates-offered-by-chartered-banks/", "html", "page table == API", "https://www.bankofcanada.ca/rates/"),
    ("C004", "BoC bond yields page", "P003", "https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/", "html", "page == API", "https://www.bankofcanada.ca/rates/"),
    ("C005", "BoC policy rate page", "P005", "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/", "html", "page == API", "https://www.bankofcanada.ca/rates/"),
    ("C006", "BoC Valet docs", "P001", "https://www.bankofcanada.ca/valet/docs", "html", "endpoints unchanged", "https://www.bankofcanada.ca/"),
    ("C007", "FRED: Canada long-term government bond yield", "P003", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IRLTLT01CAM156N", "api_csv", "monthly avg 10yr within 0.15%", "https://fred.stlouisfed.org/searchresults?st=canada%20bond"),
    ("C008", "FRED: Canada 3-month interbank", "P006", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IR3TIB01CAM156N", "api_csv", "within 0.30% of CORRA", "https://fred.stlouisfed.org/"),
    ("C009", "OECD data explorer (Canada interest rates)", "P003", "https://data-explorer.oecd.org/", "html_js", "monthly long rate within 0.15%", "https://www.oecd.org/en/data/"),
    ("C010", "BIS central bank policy rates", "P005", "https://data.bis.org/topics/CBPOL", "html_js", "policy == BoC", "https://data.bis.org/"),
    ("C011", "StatCan table viewer 10-10-0145", "P011", f"{STC}/t1/tbl1/en/tv.action?pid=1010014501", "html", "table id still live", f"{STC}/n1/en/type/data"),
    ("C012", "StatCan table viewer 34-10-0145", "P012", f"{STC}/t1/tbl1/en/tv.action?pid=3410014501", "html", "table id still live", f"{STC}/n1/en/type/data"),
    ("C013", "StatCan WDS user guide", "P015", "https://www.statcan.gc.ca/en/developers/wds/user-guide", "html", "API methods unchanged", "https://www.statcan.gc.ca/en/developers"),
    ("C014", "CMHC mortgage and consumer credit trends", "P002", "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/housing-data", "html", "avg rates direction agrees", "https://www.cmhc-schl.gc.ca/"),
    ("C015", "CMHC mortgage loan insurance premiums", "P002", "https://www.cmhc-schl.gc.ca/consumers/home-buying/mortgage-loan-insurance-for-consumers/cmhc-mortgage-loan-insurance-cost", "html", "premium schedule unchanged", "https://www.cmhc-schl.gc.ca/"),
    ("C016", "OSFI B-20 / minimum qualifying rate", "P001", "https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/residential-mortgage-underwriting-practices-procedures-guideline-2017", "html", "MQR floor 5.25% / contract+2", "https://www.osfi-bsif.gc.ca/"),
    ("C017", "OSFI financial data (bank filings)", "P009", "https://www.osfi-bsif.gc.ca/en/data-forms/open-government-osfi-financial-data", "html", "balances trend agrees", "https://www.osfi-bsif.gc.ca/"),
    ("C018", "Open Canada dataset search", "P017", "https://search.open.canada.ca/opendata/?search_text=mortgage", "html", "dataset still listed", "https://open.canada.ca/"),
    ("C019", "CREA housing market stats", "P019", "https://www.crea.ca/housing-market-stats/canadian-housing-market-stats/", "html", "national figures agree", "https://www.crea.ca/"),
    ("C020", "Statistics Canada The Daily", "P014", "https://www150.statcan.gc.ca/n1/dai-quo/index-eng.htm", "html", "release published", "https://www.statcan.gc.ca/"),
    # ---------------- Lender penalty calculators (check your IRD against theirs) ----------------
    ("C021", "RBC prepayment charges page + calculator", "P021", "https://www.rbcroyalbank.com/mortgages/mortgage-prepayment-charges.html", "html_js", "our IRD within $50 of theirs", "https://www.rbcroyalbank.com/sitemap.xml"),
    ("C022", "TD prepayment charge calculator", "P023", "https://ix0.apps.td.com/mortgage-prepayment-calculator/", "html_js", "our IRD within $50", "https://www.td.com/sitemap.xml"),
    ("C023", "Scotiabank prepayment charge calculator", "P025", "https://www.scotiabank.com/ca/en/personal/mortgages/understanding-mortgage-prepayments-charges.html", "html_js", "our IRD within $50", "https://www.scotiabank.com/sitemap.xml"),
    ("C024", "BMO prepayment charge calculator", "P027", "https://www.bmo.com/main/personal/mortgages/mortgage-calculators/prepayment-charge-calculator/", "html_js", "our IRD within $50", "https://www.bmo.com/sitemap.xml"),
    ("C025", "CIBC prepayment charge calculator", "P029", "https://www.cibc.com/en/personal-banking/mortgages/calculators/prepayment-calculator.html", "html_js", "our IRD within $50", "https://www.cibc.com/sitemap.xml"),
    ("C026", "National Bank prepayment penalty calculator", "P031", "https://www.nbc.ca/personal/mortgages/calculators/prepayment.html", "html_js", "our IRD within $50", "https://www.nbc.ca/sitemap.xml"),
    ("C027", "Tangerine prepayment calculator", "P033", "https://www.tangerine.ca/en/personal/borrow/mortgage/mortgage-prepayment-charge-calculator", "html_js", "our IRD within $50", "https://www.tangerine.ca/sitemap.xml"),
    ("C028", "Simplii prepayment calculator", "P034", "https://www.simplii.com/en/mortgages/prepayment-calculator.html", "html_js", "our IRD within $50", "https://www.simplii.com/sitemap.xml"),
    ("C029", "Desjardins prepayment penalty calculator", "P035", "https://www.desjardins.com/ca/tools/prepayment-penalty/index.jsp", "html_js", "our IRD within $50", "https://www.desjardins.com/sitemap.xml"),
    ("C030", "ATB prepayment calculator", "P039", "https://www.atb.com/resources/tools/mortgage-prepayment-calculator/", "html_js", "our IRD within $50", "https://www.atb.com/sitemap.xml"),
    ("C031", "Manulife Bank prepayment calculator", "P038", "https://www.manulifebank.ca/personal-banking/calculators.html", "html_js", "our IRD within $50", "https://www.manulifebank.ca/sitemap.xml"),
    ("C032", "First National prepayment calculator", "P052", "https://www.firstnational.ca/residential/mortgage-calculators/prepayment-calculator", "html_js", "our IRD within $50", "https://www.firstnational.ca/sitemap.xml"),
    ("C033", "MCAP rates/advice (no public penalty calculator)", "P051", "https://www.mcap.com/residential-mortgages/advice/mortgage-rates-canada", "html_js", "our IRD within $50", "https://www.mcap.com/sitemap.xml"),
    ("C034", "RMG legal/terms (prepayment terms)", "P053", "https://www.rmgmortgages.ca/rmg-legal", "html_js", "our IRD within $50", "https://www.rmgmortgages.ca/sitemap.xml"),
    ("C035", "Meridian prepayment calculator", "P073", "https://www.meridiancu.ca/personal/calculators", "html_js", "our IRD within $50", "https://www.meridiancu.ca/sitemap.xml"),
    ("C036", "Vancity renewal/prepayment info", "P071", "https://www.vancity.com/borrow/mortgages/renewing-your-mortgage", "html_js", "our IRD within $50", "https://www.vancity.com/sitemap.xml"),
    ("C037", "Coast Capital prepayment calculator", "P072", "https://www.coastcapitalsavings.com/calculators", "html_js", "our IRD within $50", "https://www.coastcapitalsavings.com/sitemap.xml"),
    ("C038", "Servus prepayment calculator", "P074", "https://servus.ca/calculators", "html_js", "our IRD within $50", "https://servus.ca/sitemap.xml"),
    ("C039", "Laurentian prepayment info", "P036", "https://www.laurentianbank.ca/en/personal/mortgages", "html", "method text unchanged", "https://www.laurentianbank.ca/sitemap.xml"),
    ("C040", "Home Trust prepayment info", "P041", "https://www.hometrust.ca/faqs/", "html", "method text unchanged", "https://www.hometrust.ca/sitemap.xml"),
    # ---------------- Third-party calculators & aggregators (independent re-scrapes) ----------------
    ("C041", "Ratehub best mortgage rates", "P061", "https://www.ratehub.ca/best-mortgage-rates", "html_js", "best 5yr fixed within 0.25%", "https://www.ratehub.ca/sitemap.xml"),
    ("C042", "Ratehub big-bank posted rates", "P021", "https://www.ratehub.ca/banks/bank-mortgage-rates", "html_js", "posted == bank page", "https://www.ratehub.ca/sitemap.xml"),
    ("C043", "Ratehub refinance penalty calculator", "P021", "https://www.ratehub.ca/mortgage-refinance-penalty", "html_js", "IRD within $100", "https://www.ratehub.ca/sitemap.xml"),
    ("C044", "WOWA mortgage rates", "P061", "https://wowa.ca/mortgage-rates", "html", "best 5yr fixed within 0.25%", "https://wowa.ca/sitemap.xml"),
    ("C045", "WOWA best 5yr fixed", "P021", "https://wowa.ca/best-mortgage-rates/5-year/fixed", "html", "posted == bank page", "https://wowa.ca/sitemap.xml"),
    ("C046", "WOWA mortgage penalty calculator", "P021", "https://wowa.ca/calculators/mortgage-penalty-calculator", "html", "IRD within $100", "https://wowa.ca/sitemap.xml"),
    ("C047", "nesto penalty calculator", "P061", "https://www.nesto.ca/calculators/mortgage-payment/mortgage-penalty-calculator/", "html_js", "IRD within $100", "https://www.nesto.ca/sitemap.xml"),
    ("C048", "LowestRates mortgage rates", "P061", "https://www.lowestrates.ca/mortgage", "html_js", "best 5yr fixed within 0.25%", "https://www.lowestrates.ca/sitemap.xml"),
    ("C049", "NerdWallet Canada", "P061", "https://www.nerdwallet.com/ca", "html", "best 5yr fixed within 0.30%", "https://www.nerdwallet.com/ca"),
    ("C050", "MoneySense", "P061", "https://www.moneysense.ca/", "html", "rate commentary agrees", "https://www.moneysense.ca/"),
    ("C051", "Mortgage Sandbox (posted vs discount, penalty)", "P021", "https://www.mortgagesandbox.com/", "html", "IRD within $100", "https://www.mortgagesandbox.com/sitemap.xml"),
    ("C052", "True North penalties & privileges", "P062", "https://www.truenorthmortgage.ca/mortgage-solutions/pre-payment-penalties-and-privileges", "html", "IRD within $100", "https://www.truenorthmortgage.ca/sitemap.xml"),
    ("C053", "Canadian Mortgage Trends (rate-change news)", "P001", "https://www.canadianmortgagetrends.com/", "html", "posted change reported same week", "https://www.canadianmortgagetrends.com/feed/"),
    ("C054", "MortgageLogic.news", "P001", "https://mortgagelogic.news/", "html", "rate moves reported", "https://mortgagelogic.news/feed/"),
    ("C055", "Canadian Mortgage Professional (mpamag)", "P001", "https://www.mpamag.com/ca", "html", "rate moves reported", "https://www.mpamag.com/ca"),
    ("C056", "RateSpy", "P061", "https://www.ratespy.com/", "html", "best rates within 0.25%", "https://www.ratespy.com/"),
    ("C057", "Mortgage Professionals Canada (consumer surveys)", "P002", "https://mortgageproscan.ca/", "html", "avg rate within 0.30%", "https://mortgageproscan.ca/"),
    ("C058", "Rates.ca mortgage rates", "P061", "https://rates.ca/mortgage-rates", "html_js", "best 5yr fixed within 0.25%", "https://rates.ca/"),
    ("C059", "WOWA best 3-year fixed (independent re-read)", "P061", "https://wowa.ca/best-mortgage-rates/3-year/fixed", "html", "best 3yr fixed within 0.25%", "https://wowa.ca/sitemap.xml"),
    ("C060", "CanWise rate table", "P068", "https://www.canwise.com/rates/ontario", "html", "== P068", "https://canwise.com/sitemap.xml"),
    # ---------------- Laws & rules that cap / define the penalty ----------------
    ("C061", "Interest Act s.10 (3-month cap after 5 years)", "IRD", "https://laws-lois.justice.gc.ca/eng/acts/I-15/page-1.html", "html", "s.10 text unchanged", "https://laws-lois.justice.gc.ca/eng/acts/I-15/"),
    ("C062", "Cost of Borrowing (Banks) Regulations", "IRD", "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2001-101/", "html", "repealed/replaced notice", "https://laws-lois.justice.gc.ca/eng/regulations/"),
    ("C063", "Financial Consumer Protection Framework Regulations", "IRD", "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2021-181/", "html", "prepayment disclosure rules", "https://laws-lois.justice.gc.ca/eng/regulations/"),
    ("C064", "Bank Act", "IRD", "https://laws-lois.justice.gc.ca/eng/acts/B-1.01/", "html", "text unchanged", "https://laws-lois.justice.gc.ca/"),
    ("C065", "Trust and Loan Companies Act", "IRD", "https://laws-lois.justice.gc.ca/eng/acts/T-19.8/", "html", "text unchanged", "https://laws-lois.justice.gc.ca/"),
    ("C066", "FCAC - mortgage prepayment penalties", "IRD", "https://www.canada.ca/en/financial-consumer-agency/services/mortgages/prepayment-penalties.html", "html", "method description unchanged", "https://www.canada.ca/en/financial-consumer-agency/services/mortgages.html"),
    ("C067", "FCAC - mortgages hub", "IRD", "https://www.canada.ca/en/financial-consumer-agency/services/mortgages.html", "html", "links live", "https://www.canada.ca/en/financial-consumer-agency.html"),
    ("C068", "FCAC - compliance/enforcement decisions", "IRD", "https://www.canada.ca/en/financial-consumer-agency/services/industry/commissioner-decisions.html", "html", "new penalty-disclosure decisions", "https://www.canada.ca/en/financial-consumer-agency.html"),
    ("C069", "OBSI (ombudsman) - search prepayment", "IRD", "https://www.obsi.ca/en/", "html", "IRD dispute outcomes", "https://www.obsi.ca/"),
    ("C070", "ADR Bank Ombuds Office", "IRD", "https://www.adrbo.ca/", "html", "IRD dispute outcomes", "https://www.adrbo.ca/"),
    ("C071", "CanLII (court cases on prepayment penalties)", "IRD", "https://www.canlii.org/en/", "html", "case law", "https://www.canlii.org/"),
    ("C072", "BCFSA (BC credit union regulator)", "IRD", "https://www.bcfsa.ca/", "html", "CU disclosure rules", "https://www.bcfsa.ca/"),
    ("C073", "FSRA Ontario", "IRD", "https://www.fsrao.ca/", "html", "CU/broker rules", "https://www.fsrao.ca/"),
    ("C074", "AMF Quebec", "IRD", "https://lautorite.qc.ca/en/general-public", "html", "Desjardins/QC rules", "https://lautorite.qc.ca/"),
    ("C075", "Ontario standard charge terms (OnLand)", "IRD", "https://www.onland.ca/ui/", "html_js", "lender filed charge terms (penalty clause)", "https://www.ontario.ca/page/land-registration"),
    # ---------------- Archives: prove a historical posted rate ----------------
    ("C076", "Wayback availability API", "P099", "https://archive.org/wayback/available?url=rbcroyalbank.com/mortgages/mortgage-rates.html", "archive", "closest snapshot exists", "https://archive.org/help/wayback_api.php"),
    ("C077", "Wayback CDX for TD rate page", "P023", "https://web.archive.org/cdx/search/cdx?url=td.com/ca/en/personal-banking/products/mortgages/mortgage-rates&output=json&limit=3", "archive", "snapshot rate == BoC posted that week", "https://archive.org/help/wayback_api.php"),
    ("C078", "Wayback CDX for Scotia rate page", "P025", "https://web.archive.org/cdx/search/cdx?url=scotiabank.com/ca/en/personal/rates-prices/mortgage-rates.html&output=json&limit=3", "archive", "snapshot rate == BoC posted", "https://archive.org/help/wayback_api.php"),
    ("C079", "Wayback CDX for BMO rate page", "P027", "https://web.archive.org/cdx/search/cdx?url=bmo.com/main/personal/mortgages/mortgage-rates/&output=json&limit=3", "archive", "snapshot rate == BoC posted", "https://archive.org/help/wayback_api.php"),
    ("C080", "Wayback CDX for CIBC rate page", "P029", "https://web.archive.org/cdx/search/cdx?url=cibc.com/en/personal-banking/mortgages/mortgage-rates.html&output=json&limit=3", "archive", "snapshot rate == BoC posted", "https://archive.org/help/wayback_api.php"),
    ("C081", "Wayback CDX for National Bank rate page", "P031", "https://web.archive.org/cdx/search/cdx?url=nbc.ca/personal/mortgages/mortgage-rates.html&output=json&limit=3", "archive", "snapshot rate == BoC posted", "https://archive.org/help/wayback_api.php"),
    ("C082", "archive.today", "P099", "https://archive.ph/", "archive", "second archive agrees", "https://archive.ph/"),
    ("C083", "Memento TimeTravel (searches every web archive)", "P099", "https://timetravel.mementoweb.org/", "archive", "any archive agrees", "http://mementoweb.org/"),
    ("C084", "Library and Archives Canada web archive", "P099", "https://webarchive.bac-lac.gc.ca/", "archive", "gov pages history", "https://library-archives.canada.ca/"),
    ("C085", "Common Crawl CDX query (latest crawl)", "P100", "https://index.commoncrawl.org/", "archive", "alternate snapshot exists", "https://commoncrawl.org/get-started"),
    # ---------------- Change signals: news, prime moves, feeds ----------------
    ("C086", "BoC press releases feed (rate decisions)", "P005", "https://www.bankofcanada.ca/content_type/press-releases/feed/", "rss", "decision date -> expect prime move next day", "https://www.bankofcanada.ca/press/"),
    ("C087", "BoC rate announcement schedule", "P005", "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/", "html", "schedule known", "https://www.bankofcanada.ca/"),
    ("C088", "Cision / Newswire Canada banking news", "P021", "https://www.newswire.ca/news-releases/financial-services-latest-news/banking-financial-services-list/", "html", "prime change releases", "https://www.newswire.ca/"),
    ("C089", "GlobeNewswire Canada", "P021", "https://www.globenewswire.com/search/keyword/prime%20rate", "html", "prime change releases", "https://www.globenewswire.com/"),
    ("C090", "Google News RSS: posted mortgage rate Canada", "P001", "https://news.google.com/rss/search?q=posted+mortgage+rate+canada&hl=en-CA&gl=CA&ceid=CA:en", "rss", "change reported", "https://news.google.com/"),
    ("C091", "Google News RSS: prime rate Canada", "P022", "https://news.google.com/rss/search?q=prime+rate+canada+bank&hl=en-CA&gl=CA&ceid=CA:en", "rss", "change reported", "https://news.google.com/"),
    ("C092", "RBC newsroom", "P021", "https://www.rbc.com/newsroom/", "html", "prime change release", "https://www.rbc.com/"),
    ("C093", "TD newsroom", "P023", "https://stories.td.com/ca/en/news", "html", "prime change release", "https://www.td.com/"),
    ("C094", "Scotiabank newsroom", "P025", "https://www.scotiabank.com/ca/en/about/news.html", "html", "prime change release", "https://www.scotiabank.com/"),
    ("C095", "BMO newsroom", "P027", "https://newsroom.bmo.com/", "html", "prime change release", "https://www.bmo.com/"),
    ("C096", "CIBC newsroom", "P029", "https://cibc.mediaroom.com/", "html", "prime change release", "https://www.cibc.com/"),
    ("C097", "National Bank press releases (prime changes)", "P031", "https://www.nbc.ca/about-us/news-media/press-release.html", "html", "prime change release", "https://www.nbc.ca/"),
    ("C098", "Reddit r/PersonalFinanceCanada search JSON", "P021", "https://www.reddit.com/r/PersonalFinanceCanada/search.json?q=IRD%20penalty&restrict_sr=1&sort=new", "api_json", "real penalty quotes to test calculator", "https://www.reddit.com/dev/api/"),
    ("C099", "Canadian Mortgage Trends RSS", "P001", "https://www.canadianmortgagetrends.com/feed/", "rss", "rate moves reported", "https://www.canadianmortgagetrends.com/"),
    ("C100", "Wikipedia - list of banks in Canada (catch new/merged lenders)", "ALL", "https://en.wikipedia.org/wiki/List_of_banks_and_credit_unions_in_Canada", "html", "registry still covers all lenders", "https://www.osfi-bsif.gc.ca/en/supervision/who-we-regulate"),
]


def _refresh_fix_from(rows, url_i, fix_i):
    """Keep 'fix_from' pointing at the CURRENT site's sitemap after a URL is replaced."""
    from urllib.parse import urlparse
    out = []
    for r in rows:
        r = list(r)
        if r[fix_i].endswith("sitemap.xml"):
            u = urlparse(r[url_i])
            r[fix_i] = f"{u.scheme}://{u.netloc}/sitemap.xml"
        out.append(tuple(r))
    return out


PRIMARY = _refresh_fix_from(PRIMARY, 4, 7)
CHECKS = _refresh_fix_from(CHECKS, 3, 6)
