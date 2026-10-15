"""100 lenders active in Ontario residential mortgages, roughly by size within each group.

No free official Ontario-only league table exists; ranking is approximate (national asset size, Ontario
branch/broker presence). Credit-union list back-check: FSRA's registry of Ontario credit unions.

    python -m renewal.ratewatch.ontario          verify all 100 (3 tries each), find rate + penalty pages -> data/ontario_lenders.csv
"""
from .paths import DATA as _DATA
import csv, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from .discover import discover
from .linkcheck import UA
from .parse import extract_rates
from .ird import POLICIES

# Merged/closed (removed after verification 2026-10-14): Hald-Nor -> Libro (2015); Lambton Financial and
# Sydenham Community -> Mainstreet; Strive Mortgage, Ontario Civil Service CU, Unity Savings: site unreachable.
# id, name, group, homepage, known rates page (blank = discover), policy key
ONTARIO = [
    ("O001", "RBC Royal Bank", "big6", "https://www.rbcroyalbank.com", "https://www.rbcroyalbank.com/mortgages/mortgage-rates.html", "RBC"),
    ("O002", "TD Canada Trust", "big6", "https://www.td.com", "https://www.td.com/ca/en/personal-banking/products/mortgages/mortgage-rates", "TD"),
    ("O003", "Scotiabank", "big6", "https://www.scotiabank.com", "https://www.scotiabank.com/ca/en/personal/rates-prices/mortgages-rates.html", "Scotiabank"),
    ("O004", "BMO Bank of Montreal", "big6", "https://www.bmo.com", "https://www.bmo.com/main/personal/mortgages/mortgage-rates/", "BMO"),
    ("O005", "CIBC", "big6", "https://www.cibc.com", "https://www.cibc.com/en/interest-rates/mortgage-rates.html", "CIBC"),
    ("O006", "National Bank of Canada", "big6", "https://www.nbc.ca", "https://www.nbc.ca/personal/mortgages/rates.html", "National Bank"),
    ("O007", "Desjardins (Ontario)", "bank", "https://www.desjardins.com", "https://www.desjardins.com/en/mortgage/mortgage-rates.html", "Desjardins"),
    ("O008", "Tangerine", "bank", "https://www.tangerine.ca", "https://www.tangerine.ca/en/rates/mortgage-rates", "Tangerine"),
    ("O009", "Simplii Financial", "bank", "https://www.simplii.com", "https://www.simplii.com/en/rates/mortgage-rates.html", "Simplii"),
    ("O010", "Equitable Bank / EQ Bank", "bank", "https://www.equitablebank.ca", "", "Equitable Bank"),
    ("O011", "Home Trust", "trust", "https://www.hometrust.ca", "https://www.hometrust.ca/rates/", "Home Trust"),
    ("O012", "Laurentian Bank", "bank", "https://www.laurentianbank.ca", "https://www.laurentianbank.ca/en/personal/rates/mortgages", "Laurentian"),
    ("O013", "B2B Bank", "bank", "https://b2bbank.com", "https://b2bbank.com/mybank/rates/index", "Laurentian"),
    ("O014", "Manulife Bank", "bank", "https://www.manulifebank.ca", "", "Manulife Bank"),
    ("O015", "Alterna Bank", "bank", "https://www.alternabank.ca", "", ""),
    ("O016", "ICICI Bank Canada", "bank", "https://www.icicibank.ca", "", ""),
    ("O017", "Wealth One Bank of Canada", "bank", "https://www.wealthonebankofcanada.com", "", ""),
    ("O018", "Haventree Bank", "bank", "https://www.haventreebank.com", "", "Haventree"),
    ("O019", "Peoples Bank / Peoples Group", "bank", "https://www.peoplesgroup.com", "", ""),
    ("O020", "Concentra Bank (Wyth)", "bank", "https://concentra.ca", "", ""),
    ("O021", "HomeEquity Bank (CHIP)", "bank", "https://www.chip.ca", "", ""),
    ("O022", "Bridgewater Bank", "bank", "https://bridgewaterbank.ca", "", "Bridgewater"),
    ("O023", "Community Trust", "trust", "https://www.communitytrust.ca", "", ""),
    ("O024", "Effort Trust", "trust", "https://www.efforttrust.ca", "", ""),
    ("O025", "Cameron Stephens Mortgage Capital", "trust", "https://cameronstephens.com", "", ""),
    ("O026", "MCAP", "monoline", "https://www.mcap.com", "", "MCAP"),
    ("O027", "First National Financial", "monoline", "https://www.firstnational.ca", "", "First National"),
    ("O028", "RMG Mortgages", "monoline", "https://www.rmgmortgages.ca", "", "RMG"),
    ("O029", "CMLS Financial", "monoline", "https://www.cmls.ca", "", "CMLS"),
    ("O030", "Merix Financial", "monoline", "https://www.merixfinancial.com", "", "Merix"),
    ("O031", "Lendwise", "monoline", "https://lendwise.com", "", "Lendwise"),
    ("O032", "Marathon Mortgage", "monoline", "https://marathonmortgage.ca", "", "Marathon"),
    ("O033", "Optimum Mortgage (National Bank)", "monoline", "https://www.nbc.ca", "https://www.nbc.ca/en/optimummortgage/brokers/rates.html", ""),
    ("O034", "Meridian Credit Union", "credit_union", "https://www.meridiancu.ca", "https://www.meridiancu.ca/personal/rates-and-fees/mortgage-and-borrowing-rates", "Credit union (generic)"),
    ("O035", "Alterna Savings", "credit_union", "https://www.alterna.ca", "https://www.alterna.ca/en/rates/mortgages", "Credit union (generic)"),
    ("O036", "DUCA Financial", "credit_union", "https://www.duca.com", "https://www.duca.com/rates", "Credit union (generic)"),
    ("O037", "FirstOntario Credit Union", "credit_union", "https://www.firstontario.com", "https://www.firstontario.com/personal/rates/", "Credit union (generic)"),
    ("O038", "Libro Credit Union", "credit_union", "https://www.libro.ca", "https://www.libro.ca/rates-fees/", "Credit union (generic)"),
    ("O039", "Kawartha Credit Union", "credit_union", "https://www.kawarthacu.com", "https://www.kawarthacu.com/rates", "Credit union (generic)"),
    ("O040", "Tandia Financial", "credit_union", "https://www.tandia.com", "https://www.tandia.com/rates", "Credit union (generic)"),
    ("O041", "Your Neighbourhood Credit Union", "credit_union", "https://www.yncu.com", "https://www.yncu.com/resources/rates/mortgage-rates", "Credit union (generic)"),
    ("O042", "Kindred Credit Union", "credit_union", "https://www.kindredcu.com", "", "Credit union (generic)"),
    ("O043", "Copperfin Credit Union", "credit_union", "https://www.copperfin.ca", "", "Credit union (generic)"),
    ("O044", "ICSavings (Italian Canadian Savings)", "credit_union", "https://www.icsavings.ca", "", "Credit union (generic)"),
    ("O045", "WFCU Credit Union", "credit_union", "https://www.wfcu.ca", "", "Credit union (generic)"),
    ("O046", "Ukrainian Credit Union", "credit_union", "https://www.ukrainiancu.com", "", "Credit union (generic)"),
    ("O047", "Buduchnist Credit Union", "credit_union", "https://www.buduchnist.com", "", "Credit union (generic)"),
    ("O048", "St. Stanislaus-St. Casimir's Polish Parishes CU", "credit_union", "https://www.polcu.com", "", "Credit union (generic)"),
    ("O049", "Mainstreet Credit Union", "credit_union", "https://mainstreetcu.ca", "https://mainstreetcu.ca/rates", "Credit union (generic)"),
    ("O050", "Northern Credit Union", "credit_union", "https://www.northerncu.com", "", "Credit union (generic)"),
    ("O051", "Sudbury Credit Union", "credit_union", "https://www.sudburycu.com", "", "Credit union (generic)"),
    ("O052", "Frontline Financial Credit Union", "credit_union", "https://www.frontlinecu.com", "", "Credit union (generic)"),
    ("O053", "Prosperity One Credit Union", "credit_union", "https://www.prosperityone.ca", "", "Credit union (generic)"),
    ("O054", "Golden Horseshoe Credit Union", "credit_union", "https://www.ghcu.ca", "", "Credit union (generic)"),
    ("O055", "Rapport Credit Union", "credit_union", "https://www.rapportcu.ca", "", "Credit union (generic)"),
    ("O056", "Parama Credit Union", "credit_union", "https://www.parama.ca", "", "Credit union (generic)"),
    ("O057", "Luminus Financial", "credit_union", "https://www.luminusfinancial.com", "", "Credit union (generic)"),
    ("O058", "Moya Financial", "credit_union", "https://www.moya.ca", "", "Credit union (generic)"),
    ("O059", "Ontario Educational Credit Union", "credit_union", "https://www.oecu.on.ca", "", "Credit union (generic)"),
    ("O060", "Healthcare & Municipal Employees CU", "credit_union", "https://www.hmecu.com", "", "Credit union (generic)"),
    ("O061", "VersaBank (London ON)", "bank", "https://www.versabank.com", "", ""),
    ("O062", "Momentum Credit Union", "credit_union", "https://www.momentumcu.ca", "", "Credit union (generic)"),
    ("O063", "PenFinancial Credit Union", "credit_union", "https://www.penfinancial.com", "", "Credit union (generic)"),
    ("O064", "Bank of China (Canada)", "bank", "https://www.bankofchina.com/ca/en/", "", ""),
    ("O065", "Encompass Credit Union", "credit_union", "https://www.encompasscu.ca", "", "Credit union (generic)"),
    ("O066", "Superior Credit Union", "credit_union", "https://www.superiorcu.com", "", "Credit union (generic)"),
    ("O067", "Pace Savings & Credit Union", "credit_union", "https://www.pacecu.ca", "", "Credit union (generic)"),
    ("O068", "Shinhan Bank Canada", "bank", "https://www.shinhan.ca", "", ""),
    ("O069", "KEB Hana Bank Canada", "bank", "https://www.kebhana.com/canada", "", ""),
    ("O070", "Comtech Fire Credit Union", "credit_union", "https://www.comtechfirecu.com", "", "Credit union (generic)"),
    ("O071", "Caisse populaire Alliance", "credit_union", "https://www.caissealliance.com", "", "Credit union (generic)"),
    ("O072", "Ganaraska Financial", "credit_union", "https://www.ganaraska.com", "", "Credit union (generic)"),
    ("O073", "SBI Canada Bank", "bank", "https://www.sbicanada.com", "", ""),
    ("O074", "Questbank (Questrade)", "bank", "https://www.questrade.com", "", ""),
    ("O075", "Fire Fighters Credit Union", "credit_union", "https://www.ffcu.ca", "", "Credit union (generic)"),
    ("O076", "Atrium Mortgage Investment Corp", "private", "https://www.atriummic.com", "", ""),
    ("O077", "Firm Capital", "private", "https://www.firmcapital.com", "", ""),
    ("O078", "CMI Financial Group", "private", "https://thecmigroup.ca", "", ""),
    ("O079", "Antrim Investments", "private", "https://www.antriminvestments.com", "", ""),
    ("O080", "Brightpath Capital", "private", "https://www.brightpathcapital.ca", "", ""),
    ("O081", "Hillmount Capital", "private", "https://www.hillmount.com", "", ""),
    ("O082", "Trez Capital", "private", "https://trezcapital.com", "", ""),
    ("O083", "Alpine Credits (home equity)", "private", "https://www.alpinecredits.ca", "", ""),
    ("O084", "Fisgard Capital", "private", "https://www.fisgard.com", "", ""),
    ("O085", "RFA Bank of Canada", "bank", "https://www.rfa.ca", "", ""),
    ("O086", "Fairstone (home equity loans)", "credit_co", "https://www.fairstone.ca", "", ""),
    ("O087", "easyfinancial (home equity)", "credit_co", "https://www.easyfinancial.com", "", ""),
    ("O088", "Spring Financial", "credit_co", "https://springfinancial.ca", "", ""),
    ("O089", "nesto", "online", "https://www.nesto.ca", "https://www.nesto.ca/mortgage-rates/", ""),
    ("O090", "True North Mortgage", "online", "https://www.truenorthmortgage.ca", "https://www.truenorthmortgage.ca/rates/ontario", ""),
    ("O091", "Home Bank (Home Trust group)", "bank", "https://www.hometrust.ca", "", "Home Trust"),
    ("O092", "Pine", "online", "https://www.pine.ca", "", ""),
    ("O093", "Neo Financial mortgages", "online", "https://www.neofinancial.com", "https://www.neofinancial.com/mortgages", ""),
    ("O094", "Perch", "online", "https://myperch.io", "", ""),
    ("O095", "CanWise (Ratehub)", "online", "https://www.canwise.com", "https://www.canwise.com/mortgage-rates/", ""),
    ("O096", "Breezeful", "online", "https://breezeful.com", "", ""),
    ("O097", "Clover Mortgage", "online", "https://www.clovermortgage.ca", "", ""),
    ("O098", "Mortgage Outlet", "online", "https://www.mortgageoutlet.ca", "", ""),
    ("O099", "MCAN Mortgage Corporation", "monoline", "https://www.mcanfinancial.com", "", ""),
    ("O100", "Scotia Mortgage Authority / broker channel", "big6", "https://www.scotiabank.com", "https://www.scotiabank.com/ca/en/personal/mortgages.html", "Scotiabank"),
]

OUT = _DATA / "ontario_lenders.csv"


def _curl(url):
    """Fallback for sites Python's SSL stack rejects (incomplete cert chains): Windows curl uses the OS store."""
    import subprocess
    try:
        p = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", UA["User-Agent"], "-w", "\n%{http_code} %{url_effective}", url],
                           capture_output=True, timeout=40)
        body, _, tail = p.stdout.decode("utf-8", "replace").rpartition("\n")
        code, _, final = tail.partition(" ")
        return int(code or 0), final, body
    except Exception:
        return 0, "", ""


def alive(url, tries=3):
    last = "?"
    for _ in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if "perfdrive" in r.url or "captcha" in r.text[:5000].lower() or r.status_code in (401, 403, 429):
                last = "BLOCKED"
            elif r.status_code < 400:
                return "OK", r.url, r.text
            else:
                last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
            if "SSL" in last:
                code, final, body = _curl(url)
                if 200 <= code < 400:
                    return "OK", final, body
    return last, "", ""


def verify(row):
    oid, name, group, home, rates_url, pol = row
    st, final_home, _ = alive(home)
    if st != "OK":
        return [oid, name, group, home, st, "", 0, "", POLICIES.get(pol, None) is not None, ""]
    if not rates_url:
        cands = discover(final_home or home, ("rates",), use_wayback=False)
        rates_url = cands[0][1] if cands else ""
    n, rst = 0, ""
    if rates_url:
        rst, _, html = alive(rates_url)
        n = len(extract_rates(html)) if html else 0
    pen = discover(final_home or home, ("penalty",), use_wayback=False)
    pen_url = pen[0][1] if pen and pen[0][0] >= 4 else ""
    note = "rates parsed" if n else ("JS/browser or hidden API needed" if rst == "OK" else rst or "no rate page found")
    return [oid, name, group, final_home or home, "OK", rates_url, n, pen_url, POLICIES.get(pol) is not None, note]


# Ontario id -> OSFI M4 filer names. M4 is CONSOLIDATED: a parent already includes its mortgage subsidiaries
# (BMO Mortgage Corp, Scotia Mortgage Corp, Equitable Trust) - never add those on top. Tangerine is a separate filer.
OSFI_NAMES = {
    "O001": ["Royal Bank of Canada"], "O002": ["The Toronto-Dominion Bank"], "O003": ["The Bank of Nova Scotia"],
    "O004": ["Bank of Montreal"],
    "O005": ["Canadian Imperial Bank of Commerce"], "O006": ["National Bank of Canada"], "O008": ["Tangerine Bank"],
    "O010": ["Equitable Bank"], "O011": ["Home Trust Company"], "O091": ["Home Bank"], "O012": ["Laurentian Bank of Canada"],
    "O013": ["B2B Bank"], "O014": ["Manulife Bank of Canada"], "O015": ["CS Alterna Bank"], "O016": ["ICICI Bank Canada"],
    "O017": ["Wealth One Bank of Canada"], "O018": ["Haventree Bank"], "O019": ["Peoples Trust Company"], "O020": ["Concentra Bank"],
    "O021": ["HomeEquity Bank"], "O022": ["Bridgewater Bank"], "O023": ["Community Trust Company"], "O024": ["The Effort Trust Company"],
    "O061": ["VersaBank"], "O064": ["Bank of China (Canada)"], "O068": ["Shinhan Bank Canada"], "O069": ["KEB Hana Bank Canada"],
    "O073": ["SBI Canada Bank"], "O074": ["Questbank"], "O085": ["RFA Bank of Canada"], "O086": ["Fairstone Bank of Canada"],
    "O099": ["MCAN Mortgage Corporation"],
}


def loan_books():
    f = OUT.parent / "loan_book_osfi.csv"
    if not f.exists():
        return {}
    book = {r["institution"]: (float(r["residential_mortgages_$M"]), r["as_of"]) for r in csv.DictReader(open(f, encoding="utf-8"))}
    out = {}
    for oid, names in OSFI_NAMES.items():
        hit = [book[n] for n in names if n in book]
        if hit:
            out[oid] = (round(sum(h[0] for h in hit)), max(h[1] for h in hit))
    return out


def main():
    with ThreadPoolExecutor(12) as ex:
        rows = list(ex.map(verify, ONTARIO))
    books = loan_books()
    for r in rows:
        b = books.get(r[0])
        r += [b[0] if b else "", f"OSFI M4 {b[1]}" if b else "credit union: FSRA / annual report; monoline/private: investor report"]
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "lender", "group", "homepage", "site_status", "rates_url", "rates_found", "penalty_url", "has_policy", "note", "residential_mortgages_$M", "book_source"])
        w.writerows(rows)
    ok = sum(r[4] == "OK" for r in rows)
    parsed = sum(r[6] > 0 for r in rows)
    print(f"{ok}/100 sites alive, {parsed} with rates parsed today, {sum(bool(r[7]) for r in rows)} penalty pages found")
    for r in rows:
        if r[4] != "OK":
            print(f"  {r[0]} {r[1]:45} {r[4]}")


if __name__ == "__main__":
    main()
