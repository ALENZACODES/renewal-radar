"""Fail-safe tests for the lender lifecycle registry and its refresh planner.

The refresh rules exist so registry data can maintain itself without ever silently losing
a lender: tombstoning takes a regulator notice, or two sources when one is the regulator,
or THREE sources when none is (John's rule); a truncated source changes nothing; and a
run that would retire too many lenders applies nothing and demands review.
"""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from renewal.ratewatch import ird, lender_registry

_spec = importlib.util.spec_from_file_location(
    "refresh_lender_registry", Path(__file__).resolve().parent.parent / "tools" / "refresh_lender_registry.py")
refresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh)

DEFS = {
    "reg_on": {"name": "Regulator ON", "regulator": True, "segment": "credit_union",
               "provinces": ["ON"], "url": ""},
    "ccua": {"name": "CCUA directory", "regulator": False, "segment": "credit_union",
             "provinces": ["ON"], "url": ""},
    "trade": {"name": "Trade list", "regulator": False, "segment": "credit_union",
              "provinces": ["ON"], "url": ""},
    "dir2": {"name": "Directory two", "regulator": False, "segment": "credit_union",
             "provinces": ["ON"], "url": ""},
}
ALL = ["reg_on", "ccua", "trade", "dir2"]


def registry_with(names, expected=ALL, last_good=None):
    reg = {"version": 1, "sources": {}, "refresh_log": [],
           "lenders": {n: {"status": "active", "successor": None, "status_since": None,
                           "status_source": "test", "status_checked": "2026-01-01", "evidence": "",
                           "kind": "credit_union", "provinces": ["ON"],
                           "expected_in": list(expected), "aliases": []} for n in names}}
    if last_good:
        for sid, count in last_good.items():
            reg["sources"][sid] = {"name": DEFS[sid]["name"], "regulator": DEFS[sid]["regulator"],
                                   "url": "", "last_good_pull": "2026-01-01", "last_good_count": count,
                                   "stale": False, "stale_since": None}
    return reg


def pulls(include, exclude_from=()):
    """Every source lists `include`, except the sources in exclude_from drop 'Alpha Credit Union'."""
    out = {}
    for sid in ALL:
        names = [n for n in include if not (sid in exclude_from and n == "Alpha Credit Union")]
        out[sid] = {"ok": True, "names": names, "error": None}
    return out


NAMES = ["Alpha Credit Union"] + [f"Filler {i} Credit Union" for i in range(10)]


def test_a_vanish_from_one_list_only_marks_unknown():
    reg = registry_with(NAMES)
    new, report, _ = refresh.plan_refresh(reg, pulls(NAMES, exclude_from=("reg_on",)), [], "2026-10-28", DEFS)
    assert new is not None
    rec = new["lenders"]["Alpha Credit Union"]
    assert rec["status"] == "unknown"           # flagged, kept fully present
    assert "Alpha Credit Union" in new["lenders"]


def test_b_regulator_notice_tombstones_with_successor():
    reg = registry_with(NAMES)
    dead = {sid: {"ok": False, "names": [], "error": "down"} for sid in ALL}
    notices = [{"lender": "Alpha Credit Union", "action": "merged", "successor": "Beta Credit Union",
                "source": "Regulator ON", "date": "2025-06-01"}]
    new, report, _ = refresh.plan_refresh(reg, dead, notices, "2026-10-28", DEFS)
    rec = new["lenders"]["Alpha Credit Union"]
    assert rec["status"] == "merged" and rec["successor"] == "Beta Credit Union"
    assert rec["status_since"] == "2025"


def test_b2_two_sources_including_regulator_tombstone():
    reg = registry_with(NAMES)
    new, report, _ = refresh.plan_refresh(
        reg, pulls(NAMES, exclude_from=("reg_on", "ccua")), [], "2026-10-28", DEFS)
    assert new["lenders"]["Alpha Credit Union"]["status"] == "ceased"


def test_c_truncated_source_aborts_and_goes_stale():
    reg = registry_with(NAMES, last_good={"reg_on": 100})
    p = pulls(NAMES, exclude_from=("reg_on",))
    p["reg_on"] = {"ok": True, "names": [f"Filler {i} Credit Union" for i in range(40)], "error": None}
    new, report, _ = refresh.plan_refresh(reg, p, [], "2026-10-28", DEFS)
    assert new is not None
    assert new["lenders"]["Alpha Credit Union"]["status"] == "active"   # nothing derived from it
    assert new["sources"]["reg_on"]["stale"] is True
    assert new["sources"]["reg_on"]["stale_since"] == "2026-10-28"
    note = lender_registry.status_note("Alpha Credit Union", new)
    assert note and "could not be re-verified" in note                  # staleness is surfaced


def test_d_mass_disappearance_applies_nothing():
    names = [f"CU {i}" for i in range(12)]
    reg = registry_with(names, expected=["reg_on", "ccua"])
    p = {sid: {"ok": True, "names": names[:4], "error": None} for sid in ALL}  # 8 of 12 vanish, twice-confirmed
    new, report, log = refresh.plan_refresh(reg, p, [], "2026-10-28", DEFS)
    assert new is None
    assert any("REVIEW REQUIRED" in line for line in report)
    assert all(r["status"] == "active" for r in reg["lenders"].values())  # input untouched


def test_e_two_nonregulator_sources_do_not_tombstone():
    reg = registry_with(NAMES)
    new, report, _ = refresh.plan_refresh(
        reg, pulls(NAMES, exclude_from=("ccua", "trade")), [], "2026-10-28", DEFS)
    rec = new["lenders"]["Alpha Credit Union"]
    assert rec["status"] == "unknown"           # John's rule: 3 sources if regulator does not


def test_f_third_nonregulator_source_tombstones():
    reg = registry_with(NAMES)
    new, report, _ = refresh.plan_refresh(
        reg, pulls(NAMES, exclude_from=("ccua", "trade", "dir2")), [], "2026-10-28", DEFS)
    assert new["lenders"]["Alpha Credit Union"]["status"] == "ceased"


def test_penalty_surfaces_merged_lender_status(tmp_path, monkeypatch):
    reg = registry_with(["First National"])
    reg["lenders"]["First National"].update(status="merged", successor="Successor Bank",
                                            status_since="2025")
    path = tmp_path / "lender_status.json"
    path.write_text(json.dumps(reg))
    monkeypatch.setattr(lender_registry, "REGISTRY_PATH", path)
    lender_registry._cache.update(mtime=None, data=None)
    policy = ird.Policy("First National", comparison="posted", term_match="nearest")
    m = ird.Mortgage(balance=400000, contract_rate=5.0, start=date(2023, 1, 1), term_months=60)
    rates = {12: 4.44, 24: 4.74, 36: 5.04, 48: 5.14, 60: 5.34, 84: 5.64, 120: 6.04}
    r = ird.penalty(m, policy, rates, date(2025, 6, 1))
    assert r["lender_status"] == "merged" and r["lender_successor"] == "Successor Bank"
    assert any("merged into Successor Bank" in n for n in r["notes"])


def test_resolve_policy_generic_credit_union_flagged():
    reg = registry_with(["Somewhere Credit Union"])
    policy, basis = lender_registry.resolve_policy("Somewhere Credit Union", reg)
    assert basis == "generic" and policy.verified is False
    assert "Generic credit-union policy" in policy.source
    assert policy.lender == "Somewhere Credit Union"
