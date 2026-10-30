"""Identify the lender from letterhead and body text."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import PageText

# code, display name, patterns. Codes match the penalty profiles where they exist.
LENDERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('rbc', 'RBC Royal Bank', (r'\bRBC\b', r'Royal Bank of Canada', r'Banque Royale')),
    ('td', 'TD Canada Trust', (r'\bTD Canada Trust\b', r'Toronto[- ]Dominion', r'\bTD Bank\b', r'\bTD\b')),
    ('bmo', 'BMO', (r'\bBMO\b', r'Bank of Montreal', r'Banque de Montréal')),
    ('scotia', 'Scotiabank', (r'Scotiabank', r'Bank of Nova Scotia', r'Scotia Mortgage', r'Banque Scotia')),
    ('cibc', 'CIBC', (r'\bCIBC\b', r'Canadian Imperial Bank')),
    ('nbc', 'National Bank', (r'National Bank of Canada', r'Banque Nationale', r'\bNBC\b')),
    ('desjardins', 'Desjardins', (r'Desjardins',)),
    ('tangerine', 'Tangerine', (r'Tangerine',)),
    ('first_national', 'First National', (r'First National Financial', r'First National')),
    ('mcap', 'MCAP', (r'\bMCAP\b',)),
    ('eq', 'Equitable Bank', (r'Equitable Bank', r'\bEQ Bank\b')),
    ('hsbc', 'HSBC', (r'\bHSBC\b',)),
    ('simplii', 'Simplii Financial', (r'Simplii',)),
    ('laurentian', 'Laurentian Bank', (r'Laurentian Bank', r'Banque Laurentienne')),
    ('atb', 'ATB Financial', (r'\bATB\b',)),
    ('manulife', 'Manulife Bank', (r'Manulife',)),
    ('alterna_savings_and_credit_union_limited', 'Alterna Savings and Credit Union Limited', (r"Alterna Savings and Credit Union", r"Alterna Savings", r"Peterborough Community Savings", r"TME Savings",)),
    ('bay_credit_union_limited', 'Bay Credit Union Limited', (r"Bay Credit Union",)),
    ('buduchnist_credit_union_limited', 'Buduchnist Credit Union Limited', (r"Buduchnist Credit Union", r"BCU Financial",)),
    ('caisse_desjardins_ontario_credit_union_inc', 'Caisse Desjardins Ontario Credit Union Inc.', (r"Caisse Desjardins Ontario Credit Union", r"Caisse Desjardins Ontario",)),
    ('caisse_populaire_alliance_limit_e', 'Caisse populaire Alliance limitée', (r"Caisse populaire Alliance limitée", r"Caisse Alliance",)),
    ('duca_financial_services_credit_union_ltd', 'DUCA Financial Services Credit Union Ltd.', (r"DUCA Financial Services Credit Union", r"DUCA",)),
    ('energy_credit_union_limited', 'Energy Credit Union Limited', (r"Energy Credit Union", r"The Energy Credit Union",)),
    ('equity_credit_union_inc', 'Equity Credit Union Inc.', (r"Equity Credit Union",)),
    ('firstontario_credit_union_limited', 'FirstOntario Credit Union Limited', (r"FirstOntario Credit Union", r"FirstOntario", r"Creative Arts Financial", r"Saven Financial",)),
    ('fort_york_community_credit_union_limited', 'Fort York Community Credit Union Limited', (r"Fort York Community Credit Union",)),
    ('frontline_financial_credit_union_limited', 'Frontline Financial Credit Union Limited', (r"Frontline Financial Credit Union", r"Frontline Financial",)),
    ('ganaraska_credit_union_ltd', 'Ganaraska Credit Union Ltd.', (r"Ganaraska Credit Union",)),
    ('golden_horseshoe_credit_union_limited', 'Golden Horseshoe Credit Union Limited', (r"Golden Horseshoe Credit Union",)),
    ('healthcare_and_municipal_employees_credit_union_', "Healthcare and Municipal Employees' Credit Union Limited", (r"Healthcare and Municipal Employees' Credit Union", r"HMECU",)),
    ('italian_canadian_savings_credit_union_limited', 'Italian Canadian Savings & Credit Union Limited', (r"Italian Canadian Savings \& Credit Union", r"IC Savings",)),
    ('kindred_credit_union_limited', 'Kindred Credit Union Limited', (r"Kindred Credit Union",)),
    ('kingston_community_credit_union_limited', 'Kingston Community Credit Union Limited', (r"Kingston Community Credit Union",)),
    ('korean_toronto_credit_union_limited', 'Korean (Toronto) Credit Union Limited', (r"Korean \(Toronto\) Credit Union",)),
    ('korean_catholic_church_credit_union_limited', 'Korean Catholic Church Credit Union Limited', (r"Korean Catholic Church Credit Union",)),
    ('l_i_u_n_a_local_183_credit_union_limited', 'L.I.U.N.A. Local 183 Credit Union Limited', (r"L\.I\.U\.N\.A\. Local 183 Credit Union", r"LIUNA Local 183 Credit Union",)),
    ('libro_credit_union_limited', 'Libro Credit Union Limited', (r"Libro Credit Union", r"Libro", r"Kawartha Financial Services",)),
    ('lighthouse_credit_union_limited', 'Lighthouse Credit Union Limited', (r"Lighthouse Credit Union",)),
    ('luminus_financial_services_credit_union_limited', 'Luminus Financial Services & Credit Union Limited', (r"Luminus Financial Services \& Credit Union", r"Luminus Financial",)),
    ('mainstreet_credit_union_limited', 'Mainstreet Credit Union Limited', (r"Mainstreet Credit Union",)),
    ('meridian_credit_union_limited', 'Meridian Credit Union Limited', (r"Meridian Credit Union", r"Meridian",)),
    ('motor_city_community_credit_union_limited', 'Motor City Community Credit Union Limited', (r"Motor City Community Credit Union",)),
    ('moya_financial_credit_union_limited', 'Moya Financial Credit Union Limited', (r"Moya Financial Credit Union", r"Moya Financial",)),
    ('northern_birch_credit_union_limited', 'Northern Birch Credit Union Limited', (r"Northern Birch Credit Union",)),
    ('northern_credit_union_limited', 'Northern Credit Union Limited', (r"Northern Credit Union",)),
    ('ontario_educational_credit_union_limited', 'Ontario Educational Credit Union Limited', (r"Ontario Educational Credit Union",)),
    ('ontario_provincial_police_association_credit_uni', 'Ontario Provincial Police Association Credit Union Limited', (r"Ontario Provincial Police Association Credit Union", r"OPPA Credit Union",)),
    ('op_credit_union_limited', 'OP Credit Union Limited', (r"OP Credit Union",)),
    ('oshawa_community_credit_union_limited', 'Oshawa Community Credit Union Limited', (r"Oshawa Community Credit Union",)),
    ('parama_credit_union_limited', 'Parama Credit Union Limited', (r"Parama Credit Union",)),
    ('pathwise_credit_union_limited', 'Pathwise Credit Union Limited', (r"Pathwise Credit Union",)),
    ('penfinancial_credit_union_limited', 'PenFinancial Credit Union Limited', (r"PenFinancial Credit Union", r"PenFinancial",)),
    ('police_credit_union_limited', 'Police Credit Union Limited', (r"Police Credit Union", r"The Police Credit Union",)),
    ('resurrection_credit_union_limited', 'Resurrection Credit Union Limited', (r"Resurrection Credit Union", r"RCU Credit Union",)),
    ('southwest_regional_credit_union_ltd', 'Southwest Regional Credit Union Ltd.', (r"Southwest Regional Credit Union",)),
    ('st_stanislaus_st_casimir_s_polish_parishes_credi', "St. Stanislaus-St. Casimir's Polish Parishes Credit Union Limited", (r"St\. Stanislaus\-St\. Casimir's Polish Parishes Credit Union", r"St\. Stanislaus\-St\. Casimir's", r"Blue Group Savings",)),
    ('sudbury_credit_union_limited', 'Sudbury Credit Union Limited', (r"Sudbury Credit Union",)),
    ('taiwanese_canadian_toronto_credit_union_limited', 'Taiwanese - Canadian Toronto Credit Union Limited', (r"Taiwanese \- Canadian Toronto Credit Union", r"Taiwanese\-Canadian Toronto Credit Union",)),
    ('talka_credit_union_limited', 'Talka Credit Union Limited', (r"Talka Credit Union",)),
    ('thorold_community_credit_union_limited', 'Thorold Community Credit Union Limited', (r"Thorold Community Credit Union",)),
    ('ukrainian_credit_union_limited', 'Ukrainian Credit Union Limited', (r"Ukrainian Credit Union",)),
    ('windsor_family_credit_union_limited', 'Windsor Family Credit Union Limited', (r"Windsor Family Credit Union", r"WFCU Credit Union", r"WFCU", r"Rapport", r"Omnia Direct",)),
    ('your_credit_union_limited', 'Your Credit Union Limited', (r"Your Credit Union",)),
    ('your_neighbourhood_credit_union_limited', 'Your Neighbourhood Credit Union Limited', (r"Your Neighbourhood Credit Union", r"YNCU", r"Community First",)),
    ('1st_choice_savings_and_credit_union_ltd', '1st Choice Savings and Credit Union Ltd.', (r"1st Choice Savings and Credit Union", r"1st Choice Savings",)),
    ('bow_valley_credit_union_ltd', 'Bow Valley Credit Union Ltd', (r"Bow Valley Credit Union",)),
    ('calgary_police_credit_union_limited', 'Calgary Police Credit Union Limited', (r"Calgary Police Credit Union",)),
    ('christian_credit_union_ltd', 'Christian Credit Union Ltd.', (r"Christian Credit Union",)),
    ('khalsa_credit_union_alberta_limited', 'Khalsa Credit Union (Alberta) Limited', (r"Khalsa Credit Union \(Alberta\)",)),
    ('lakeland_credit_union_ltd', 'Lakeland Credit Union Ltd.', (r"Lakeland Credit Union",)),
    ('rocky_credit_union_ltd', 'Rocky Credit Union Ltd.', (r"Rocky Credit Union",)),
    ('servus_credit_union_ltd', 'Servus Credit Union Ltd.', (r"Servus Credit Union", r"Servus",)),
    ('transcanada_credit_union_ltd', 'TransCanada Credit Union Ltd.', (r"TransCanada Credit Union",)),
    ('vermilion_credit_union_limited', 'Vermilion Credit Union Limited', (r"Vermilion Credit Union",)),
    ('vision_credit_union_ltd', 'Vision Credit Union Ltd.', (r"Vision Credit Union",)),
    ('beem_credit_union', 'Beem Credit Union', (r"Beem Credit Union",)),
    ('bulkley_valley_credit_union', 'Bulkley Valley Credit Union', (r"Bulkley Valley Credit Union",)),
    ('cascadia_credit_union', 'Cascadia Credit Union', (r"Cascadia Credit Union",)),
    ('coastal_community_credit_union', 'Coastal Community Credit Union', (r"Coastal Community Credit Union",)),
    ('community_savings_credit_union', 'Community Savings Credit Union', (r"Community Savings Credit Union", r"Aria Savings",)),
    ('creston_district_credit_union', 'Creston & District Credit Union', (r"Creston \& District Credit Union",)),
    ('greater_vancouver_community_credit_union', 'Greater Vancouver Community Credit Union', (r"Greater Vancouver Community Credit Union", r"GVC Credit Union",)),
    ('khalsa_credit_union', 'Khalsa Credit Union', (r"Khalsa Credit Union",)),
    ('kootenay_savings_credit_union', 'Kootenay Savings Credit Union', (r"Kootenay Savings Credit Union",)),
    ('ladysmith_district_credit_union', 'Ladysmith & District Credit Union', (r"Ladysmith \& District Credit Union",)),
    ('lake_view_credit_union', 'Lake View Credit Union', (r"Lake View Credit Union",)),
    ('nelson_district_credit_union', 'Nelson & District Credit Union', (r"Nelson \& District Credit Union",)),
    ('northern_savings_credit_union', 'Northern Savings Credit Union', (r"Northern Savings Credit Union",)),
    ('salmon_arm_savings_and_credit_union', 'Salmon Arm Savings and Credit Union', (r"Salmon Arm Savings and Credit Union",)),
    ('sharons_credit_union', 'Sharons Credit Union', (r"Sharons Credit Union",)),
    ('stellervista_credit_union', 'StellerVista Credit Union', (r"StellerVista Credit Union",)),
    ('vancouver_city_savings_credit_union', 'Vancouver City Savings Credit Union', (r"Vancouver City Savings Credit Union", r"Vancity",)),
    ('vancouver_firefighters_credit_union', "Vancouver Firefighters' Credit Union", (r"Vancouver Firefighters' Credit Union",)),
    ('vantageone_credit_union', 'VantageOne Credit Union', (r"VantageOne Credit Union",)),
    ('williams_lake_and_district_credit_union', 'Williams Lake and District Credit Union', (r"Williams Lake and District Credit Union",)),
    ('momentum_credit_union_limited', 'Momentum Credit Union Limited', (r"Momentum Credit Union",)),
    ('rapport_credit_union_limited', 'Rapport Credit Union Limited', (r"Rapport Credit Union",)),
    ('smiths_falls_community_credit_union_limited', 'Smiths Falls Community Credit Union Limited', (r"Smiths Falls Community Credit Union",)),
    ('copperfin_credit_union_limited', 'Copperfin Credit Union Limited', (r"Copperfin Credit Union",)),
    ('dundalk_district_credit_union_limited', 'Dundalk District Credit Union Limited', (r"Dundalk District Credit Union",)),
    ('adjala_credit_union_limited', 'Adjala Credit Union Limited', (r"Adjala Credit Union",)),
    ('comtech_fire_credit_union_limited', 'Comtech Fire Credit Union Limited', (r"Comtech Fire Credit Union",)),
    ('tandia_financial_credit_union_limited', 'Tandia Financial Credit Union Limited', (r"Tandia Financial Credit Union",)),
    ('kawartha_credit_union_limited', 'Kawartha Credit Union Limited', (r"Kawartha Credit Union",)),
    ('finnish_credit_union_limited', 'Finnish Credit Union Limited', (r"Finnish Credit Union",)),
    ('connect_first_credit_union_ltd', 'Connect First Credit Union Ltd', (r"Connect First Credit Union",)),
    ('abcu_credit_union_ltd', 'ABCU Credit Union Ltd', (r"ABCU Credit Union",)),
    ('encompass_credit_union_ltd', 'Encompass Credit Union Ltd.', (r"Encompass Credit Union",)),
    ('pincher_creek_credit_union_limited', 'Pincher Creek Credit Union Limited', (r"Pincher Creek Credit Union",)),
    ('spark_the_energy_credit_union_limited', 'Spark The Energy Credit Union Limited', (r"Spark The Energy Credit Union",)),
    ('gulf_and_fraser_fishermen_s_credit_union', "Gulf and Fraser Fishermen's Credit Union", (r"Gulf and Fraser Fishermen's Credit Union",)),
    ('interior_savings_credit_union', 'Interior Savings Credit Union', (r"Interior Savings Credit Union",)),
    ('blueshore_financial_credit_union', 'BlueShore Financial Credit Union', (r"BlueShore Financial Credit Union",)),
    ('compensation_employees_credit_union', 'Compensation Employees Credit Union', (r"Compensation Employees Credit Union",)),
    ('north_peace_savings_and_credit_union', 'North Peace Savings and Credit Union', (r"North Peace Savings and Credit Union",)),
    ('grand_forks_credit_union', 'Grand Forks Credit Union', (r"Grand Forks Credit Union",)),
    ('osoyoos_credit_union', 'Osoyoos Credit Union', (r"Osoyoos Credit Union",)),
    ('revelstoke_credit_union', 'Revelstoke Credit Union', (r"Revelstoke Credit Union",)),
    ('summerland_credit_union', 'Summerland Credit Union', (r"Summerland Credit Union",)),
    ('ccec_credit_union', 'CCEC Credit Union', (r"CCEC Credit Union",)),
    ('first_credit_union', 'First Credit Union', (r"First Credit Union",)),
    ('columbia_valley_credit_union', 'Columbia Valley Credit Union', (r"Columbia Valley Credit Union",)),
    ('integris_credit_union', 'Integris Credit Union', (r"Integris Credit Union",)),
    ('prospera_credit_union', 'Prospera Credit Union', (r"Prospera Credit Union",)),
    ('sunshine_coast_credit_union', 'Sunshine Coast Credit Union', (r"Sunshine Coast Credit Union",)),
    ('heritage_credit_union', 'Heritage Credit Union', (r"Heritage Credit Union",)),
    ('east_kootenay_community_credit_union', 'East Kootenay Community Credit Union', (r"East Kootenay Community Credit Union",)),
    ('first_west_credit_union', 'First West Credit Union', (r"First West Credit Union",)),
    ('coast_capital_savings', 'Coast Capital Savings', (r"Coast Capital Savings",)),
    ('rmg', 'RMG', (r"RMG", r"RMG Mortgages",)),
    ('mcan', 'MCAN', (r"MCAN", r"MCAN Home Mortgage", r"MCAN Financial",)),
    ('merix', 'Merix', (r"Merix", r"MERIX Financial", r"Paradigm Quest",)),
    ('cmls', 'CMLS', (r"CMLS", r"CMLS Financial",)),
    ('marathon', 'Marathon', (r"Marathon", r"Marathon Mortgage",)),
    ('strive', 'Strive', (r"Strive", r"Strive Capital",)),
    ('home_trust', 'Home Trust', (r"Home Trust", r"Home Trust Company",)),
    ('radius_financial', 'Radius Financial', (r"Radius Financial",)),
    ('nesto', 'Nesto', (r"Nesto",)),
    ('pine', 'Pine', (r"Pine", r"Pine Canada Lending", r"Pine Financial",)),
    ('think_financial', 'THINK Financial', (r"THINK Financial", r"True North Mortgage",)),
    ('canwise_financial', 'CanWise Financial', (r"CanWise Financial", r"CanWise",)),
    ('neo_financial', 'Neo Financial', (r"Neo Financial", r"Neo Mortgage",)),
    ('b2b_bank', 'B2B Bank', (r"B2B Bank",)),
    ('icici_bank_canada', 'ICICI Bank Canada', (r"ICICI Bank Canada", r"ICICI Bank",)),
    ('wealth_one_bank_of_canada', 'Wealth One Bank of Canada', (r"Wealth One Bank of Canada", r"WealthONE", r"Wealth One",)),
    ('community_trust', 'Community Trust', (r"Community Trust", r"Community Trust Company", r"QuestMortgage",)),
    ('lendwise', 'Lendwise', (r"Lendwise",)),
)


@dataclass(frozen=True)
class LenderMatch:
    code: str
    name: str
    score: float
    evidence: str


def identify(pages: tuple[PageText, ...]) -> LenderMatch | None:
    """Score each lender: letterhead (first 8 lines of page 1) counts triple."""
    if not pages:
        return None
    head = '\n'.join(pages[0].text.splitlines()[:8])
    body = '\n'.join(p.text for p in pages)
    best: LenderMatch | None = None
    for code, name, patterns in LENDERS:
        score = 0.0
        evidence = ''
        for pattern in patterns:
            rx = re.compile(pattern)
            in_head = len(rx.findall(head))
            in_body = len(rx.findall(body))
            if in_body and not evidence:
                m = rx.search(body)
                evidence = body[max(0, m.start() - 30): m.end() + 30].replace('\n', ' ') if m else ''
            score += in_head * 3 + in_body
        if score and (best is None or score > best.score):
            best = LenderMatch(code, name, score, evidence.strip())
    return best
