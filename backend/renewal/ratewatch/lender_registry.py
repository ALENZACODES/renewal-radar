"""Lender lifecycle registry: is this lender still in business, and under what name?

Penalty policies (ird.POLICIES) say how a lender's charge is computed; this registry says whether
the lender still exists. Credit unions merge constantly, and a homeowner's "dead" lender usually
lives on inside a successor — so entries are never deleted, only tombstoned with their successor.

Data lives in lender_status.json beside this module and is maintained by
tools/refresh_lender_registry.py under three fail-safes (see that file): a lender is tombstoned
only on a regulator merger/wind-up notice, or on two independent sources when one of them is the
regulator, or on three independent sources when none is; a stale or truncated source changes
nothing and is flagged instead; and a refresh that would shrink the active list implausibly
applies nothing and demands review.

penalty() surfaces the status in every result ("lender_status", plus a plain-language note for
merged/ceased lenders and for lenders whose status could not be re-verified because a source is
stale). Lenders with no dedicated policy in ird.POLICIES resolve through resolve_policy(): a
registry credit union gets the generic credit-union policy, clearly flagged as generic — it is
an estimate basis, never presented as that lender's calibrated method.
"""
import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("lender_status.json")

_DEFAULT = {"status": "unknown", "successor": None, "status_since": None, "status_source": "",
            "status_checked": "", "evidence": "not in the lender status registry",
            "kind": "", "provinces": [], "expected_in": [], "aliases": []}

_cache = {"mtime": None, "data": None}


def normalize_name(name: str) -> str:
    """Matching key for lender names across source lists: casefolded, punctuation-free, with the
    legal-form noise that varies between lists removed."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").casefold())
    s = re.sub(r"\b(the|inc|corp|corporation|ltd|limited|llc|lp|financial group)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_registry(path=None) -> dict:
    path = Path(path) if path else REGISTRY_PATH
    try:
        mtime = path.stat().st_mtime
        if _cache["mtime"] != (str(path), mtime):
            data = json.loads(path.read_text())
            _cache.update(mtime=(str(path), mtime), data=data)
        return _cache["data"]
    except Exception:
        return {"version": 1, "lenders": {}, "sources": {}, "refresh_log": []}


def _find(name: str, registry: dict):
    lenders = registry.get("lenders", {})
    if name in lenders:
        return name, lenders[name]
    key = normalize_name(name)
    for display, rec in lenders.items():
        if normalize_name(display) == key:
            return display, rec
        if any(normalize_name(a) == key for a in rec.get("aliases", [])):
            return display, rec
    return None, None


def status_for(name: str, registry: dict | None = None) -> dict:
    registry = load_registry() if registry is None else registry
    _, rec = _find(name, registry)
    if rec is None:
        return dict(_DEFAULT)
    return {**_DEFAULT, **rec}


def stale_sources_for(name: str, registry: dict) -> list[str]:
    """Names of this lender's covering sources currently flagged stale."""
    _, rec = _find(name, registry)
    if rec is None:
        return []
    sources = registry.get("sources", {})
    return [sources[sid].get("name", sid) for sid in rec.get("expected_in", [])
            if sources.get(sid, {}).get("stale")]


def status_note(name: str, registry: dict | None = None) -> str | None:
    """The plain-language status note penalty() appends, or None when there is nothing to flag."""
    registry = load_registry() if registry is None else registry
    rec = status_for(name, registry)
    status = rec["status"]
    since = f" in {rec['status_since']}" if rec.get("status_since") else ""
    if status == "merged" and rec.get("successor"):
        return (f"Lender status: {name} merged into {rec['successor']}{since} — this estimate follows the "
                f"successor's published method where the registry has one; the successor confirms the "
                f"actual charge.")
    if status == "merged":
        return (f"Lender status: {name} merged into another lender{since} — treat this estimate as "
                f"indicative only; the successor confirms the actual charge.")
    if status == "ceased":
        return (f"Lender status: {name} is no longer in business{since} — this estimate follows its last "
                f"published method; the successor or administrator confirms the actual charge.")
    stale = stale_sources_for(name, registry)
    if stale:
        return (f"Lender status: {name}'s status could not be re-verified on the last registry refresh "
                f"({stale[0]} is stale) — treat this estimate with extra caution.")
    if status == "unknown" and rec.get("status_checked"):
        return (f"Lender status: {name} is flagged for verification (missing from a source list) — "
                f"treat this estimate with extra caution.")
    return None


def resolve_policy(name: str, registry: dict | None = None):
    """(Policy, basis) for a lender name: its own calibrated/template policy from ird.POLICIES
    (basis "own"), a registry credit union on the clearly-flagged generic credit-union policy
    (basis "generic"), or (None, None) when the lender is not known at all."""
    from .ird import POLICIES, Policy
    registry = load_registry() if registry is None else registry
    display, rec = _find(name, registry)
    for lender_name, policy in POLICIES.items():
        if lender_name == name or (display and lender_name == display):
            return policy, "own"
    if rec is not None and rec.get("kind") == "credit_union":
        generic = POLICIES["Credit union (generic)"]
        return Policy(display or name, comparison=generic.comparison, term_match=generic.term_match,
                      verified=False,
                      source="Generic credit-union policy — this credit union's own published charge "
                             "terms were not located; estimate only, not a calibrated method."), "generic"
    return None, None
