"""Comparison rates for lenders whose penalty is NOT measured against their own posted mortgage rates.

Each lender's own calculator code names its comparison:
- Equitable Bank: Government of Canada 1-year T-bill (daily) and 2/3/5-year benchmark bond yields (Bank of Canada)
- Bridgewater Bank: Government of Canada 1-5 year bond yields, from the feed its calculator loads (ama.ab.ca)
- Haventree Bank: its published reinvestment rates by remaining-term band (its calculator page)
- Laurentian Bank: its reference rates (loaded from its CMS at runtime; not published in a readable form)

table_for(policy, as_of) returns (table, label) for these lenders, or None for every other lender. A table is never
borrowed from another kind of rate: when the right comparison is not available the deal is marked "needs data".
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests

from . import history
from .linkcheck import UA

BRIDGEWATER_BONDS_URL = "https://ama.ab.ca/api/bondrate/current"
HAVENTREE_CALCULATOR_URL = "https://www.haventreebank.com/en-CA/mortgages/pre-payment-calculator"
SPECIAL = ("equitable", "bridgewater", "haventree", "laurentian")


def _stored(source: str, as_of: date, kind: str, rtype: str = "yield", max_age_days: int = 10):
    table, day = history.table_on(source, as_of, rtype=rtype, kind=kind, max_age_days=max_age_days)
    return table, day


def equitable_yields(as_of: date, fetch_live: bool = True):
    """{12: 1-year T-bill, 24/36/60: benchmark bonds} from the Bank of Canada series stored by history.official()."""
    bonds, bday = _stored("GOC", as_of, "bond")
    tbill, tday = _stored("GOC", as_of, "tbill")
    if (not bonds or not tbill) and fetch_live and as_of >= date.today():
        try:
            history.official(start=(as_of - timedelta(days=30)).isoformat())
        except Exception:                                   # noqa: BLE001 - stored figures stay the answer
            pass
        bonds, bday = _stored("GOC", as_of, "bond")
        tbill, tday = _stored("GOC", as_of, "tbill")
    table = {k: bonds[k] for k in (24, 36, 60) if k in bonds}
    if 12 in tbill:
        table[12] = tbill[12]
    if len(table) < 4:
        return {}, "Bank of Canada T-bill / bond yields not available for this date"
    return table, f"Bank of Canada T-bill and benchmark bond yields ({max(bday, tday)})"


def bridgewater_bonds(as_of: date, fetch_live: bool = True):
    """Bridgewater's calculator bond feed: terms 1-5 years -> {12, 24, 36, 48, 60}."""
    table, day = _stored("BWB_BONDS", as_of, "bond")
    if (len(table) < 5) and fetch_live and as_of >= date.today():
        try:
            d = requests.get(BRIDGEWATER_BONDS_URL, headers=UA, timeout=30).json()
            rows = [(int(t["term"]) * 12, "bond", "yield", float(t["rate"])) for t in d.get("terms", [])
                    if 1 <= int(t["term"]) <= 10]
            if rows:
                history.save("BWB_BONDS", as_of.isoformat(), rows, "api")
                table, day = _stored("BWB_BONDS", as_of, "bond")
        except Exception:                                   # noqa: BLE001
            pass
    table = {k: table[k] for k in (12, 24, 36, 48, 60) if k in table}
    if len(table) < 5:
        return {}, "Bridgewater's bond yield feed not available for this date"
    return table, f"Government of Canada bond yields from Bridgewater's calculator feed ({day})"


def haventree_reinvestment_rows(html: str) -> list:
    """Haventree's calculator page carries its reinvestment table in the page data:
    "reinvestmentRates":[{"minMonths":1,"maxMonths":17,"rate":3.54},...]. Bands map to 12/24/36/48."""
    text = html.replace('\\"', '"')
    m = re.search(r'"reinvestmentRates":(\[.*?\])', text)
    if not m:
        return []
    try:
        bands = json.loads(m.group(1).replace('"$Infinity"', "null"))
    except ValueError:
        return []
    keys = {1: 12, 18: 24, 30: 36, 42: 48}
    return [(keys[b["minMonths"]], "reinvest", "rate", float(b["rate"])) for b in bands if b.get("minMonths") in keys]


def haventree_reinvestment(as_of: date, fetch_live: bool = True):
    table, day = history.table_on("HAVENTREE_REINVEST", as_of, rtype="rate", kind="reinvest", max_age_days=31)
    if len(table) < 4 and fetch_live and as_of >= date.today():
        try:
            rows = haventree_reinvestment_rows(requests.get(HAVENTREE_CALCULATOR_URL, headers=UA, timeout=30).text)
            if rows:
                history.save("HAVENTREE_REINVEST", as_of.isoformat(), rows, "html")
                table, day = history.table_on("HAVENTREE_REINVEST", as_of, rtype="rate", kind="reinvest", max_age_days=31)
        except Exception:                                   # noqa: BLE001
            pass
    if len(table) < 4:
        return {}, "Haventree's reinvestment rates not available for this date"
    return table, f"Haventree's published reinvestment rates ({day})"


def table_for(policy, as_of: date, fetch_live: bool = True):
    conv = getattr(policy, "months_convention", "")
    if conv not in SPECIAL:
        return None
    if conv == "equitable":
        return equitable_yields(as_of, fetch_live)
    if conv == "bridgewater":
        return bridgewater_bonds(as_of, fetch_live)
    if conv == "haventree":
        return haventree_reinvestment(as_of, fetch_live)
    return {}, "Laurentian's reference rates (its calculator loads them at runtime; not published in a readable form)"
