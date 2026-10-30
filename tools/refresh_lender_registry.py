"""Refresh the lender lifecycle registry from the authoritative lists — safely.

    python tools/refresh_lender_registry.py [--apply] [--pulls-dir DIR] [--notices FILE]

Dry-run by default: the tool prints (and saves) a change report and changes nothing.
--apply writes the updated registry data — but only when every fail-safe passes.

The registry (backend/renewal/ratewatch/lender_status.json) tracks whether each lender is
active, merged, ceased or unknown, and into whom a merged lender went. Lenders are never
deleted: a dead lender is tombstoned, because a homeowner's mortgage with that lender still
exists and its history must keep working.

Fail-safes (all three, each with tests in tests/test_lender_registry.py):

1. TOMBSTONE THRESHOLD. Disappearing from one list never tombstones a lender; it marks the
   lender "unknown — verify" and keeps it fully present. Tombstoning (merged/ceased) needs
   independent confirmation:
     - a single formal regulator merger/wind-up notice suffices on its own;
     - otherwise two independent sources when at least one of them is the regulator;
     - otherwise THREE independent sources (John's rule: "3 sources if regulator does not").
2. STALE / TRUNCATED-SOURCE GUARD. A source that is unreachable, or that returns a list more
   than 10% smaller than its last good pull, is unusable for that run: no change is derived
   from it, last-known-good data is kept, and the source is flagged STALE with the date. Stale
   or unverified lender status is surfaced in penalty outputs, not hidden.
3. SANITY FLOOR + AUDIT LOG. If a run would reduce the active-lender count by more than a
   small threshold (3 lenders or 2% of the active list, whichever is larger), the run flags
   itself REVIEW REQUIRED and applies nothing. Every run appends a dated entry to the
   registry's refresh log (source, counts, changes proposed/applied), so any change can be
   reconstructed later.

Sources and the segments they cover:
  fsra_cu_on    FSRA list of Ontario credit unions and caisses populaires (regulator)
  alberta_cu    Alberta Treasury Board and Finance list of Alberta credit unions (regulator)
  bcfsa_cu      BCFSA list of BC credit unions (regulator)
  ccua          Canadian Credit Union Association member directory
  cmhc_approved CMHC approved lender list (monolines and other approved mortgage lenders)
"""
import argparse
import copy
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from renewal.ratewatch.lender_registry import REGISTRY_PATH, normalize_name  # noqa: E402

SHRINK_TOLERANCE = 0.10
REVIEW_DROP_ABS = 3
REVIEW_DROP_PCT = 0.02

SOURCE_DEFS = {
    "fsra_cu_on": {"name": "FSRA — Ontario credit unions and caisses populaires", "regulator": True,
                   "segment": "credit_union", "provinces": ["ON"],
                   "url": "https://www.fsrao.ca/licensing/credit-unions-and-caisses-populaires"},
    "alberta_cu": {"name": "Alberta Treasury Board and Finance — Alberta credit unions", "regulator": True,
                   "segment": "credit_union", "provinces": ["AB"],
                   "url": "https://www.alberta.ca/credit-unions"},
    "bcfsa_cu": {"name": "BCFSA — BC credit unions", "regulator": True,
                 "segment": "credit_union", "provinces": ["BC"],
                 "url": "https://www.bcfsa.ca/public-resources/financial-institutions/credit-unions"},
    "ccua": {"name": "CCUA — Canadian Credit Union Association member directory", "regulator": False,
             "segment": "credit_union", "provinces": ["ON", "AB", "BC"],
             "url": "https://ccua.com/find-a-credit-union/"},
    "cmhc_approved": {"name": "CMHC — approved lenders", "regulator": False,
                      "segment": "lender", "provinces": ["ON", "AB", "BC"],
                      "url": "https://www.cmhc-schl.gc.ca/professionals/project-funding-and-mortgage-financing/mortgage-financing/approved-lenders"},
}


def _match_key(registry: dict) -> dict:
    """normalized name (display or alias) -> display name, for every registry lender."""
    out = {}
    for display, rec in registry.get("lenders", {}).items():
        out[normalize_name(display)] = display
        for alias in rec.get("aliases", []):
            out[normalize_name(alias)] = display
    return out


def plan_refresh(registry: dict, pulls: dict, notices: list, today: str,
                 source_defs: dict = SOURCE_DEFS):
    """Pure planning core (unit-tested without any network).

    pulls:   {source_id: {"ok": bool, "names": [display names as published], "error": str|None}}
    notices: [{"lender": str, "action": "merged"|"ceased", "successor": str|None,
               "source": str, "date": "YYYY-MM-DD"}] — formal REGULATOR merger/wind-up notices.
    Returns (new_registry | None, report_lines, log_entry). new_registry is None when the
    sanity floor trips (REVIEW REQUIRED): nothing is applied, not even stale flags.
    """
    working = copy.deepcopy(registry)
    working.setdefault("lenders", {})
    working.setdefault("sources", {})
    working.setdefault("refresh_log", [])
    for sid, sdef in source_defs.items():
        working["sources"].setdefault(sid, {"name": sdef["name"], "regulator": sdef["regulator"],
                                             "url": sdef["url"], "last_good_pull": None,
                                             "last_good_count": 0, "stale": False, "stale_since": None})
    report, changes = [], []

    # --- fail-safe 2: decide which sources are usable this run -------------------------------
    usable, pull_names = {}, {}
    for sid, sdef in source_defs.items():
        meta = working["sources"][sid]
        raw = pulls.get(sid)
        if not raw or not raw.get("ok"):
            usable[sid] = False
            report.append(f"SOURCE {sid} ({sdef['name']}): unreachable "
                          f"({(raw or {}).get('error') or 'no pull'}) — unusable this run, flagged STALE")
            continue
        names = {normalize_name(n) for n in raw.get("names", []) if n and n.strip()}
        pull_names[sid] = names
        last_good = meta.get("last_good_count") or 0
        if last_good and len(names) < (1 - SHRINK_TOLERANCE) * last_good:
            usable[sid] = False
            report.append(f"SOURCE {sid} ({sdef['name']}): returned {len(names)} entries vs last good "
                          f"{last_good} (>10% shrink) — treated as truncated, unusable this run, "
                          f"flagged STALE; last-known-good data kept")
        else:
            usable[sid] = True
            report.append(f"SOURCE {sid} ({sdef['name']}): {len(names)} entries, usable")

    def mark_stale():
        for sid in source_defs:
            if not usable[sid] and not working["sources"][sid].get("stale"):
                working["sources"][sid]["stale"] = True
                working["sources"][sid]["stale_since"] = today

    # --- regulator notices: a single formal notice tombstones on its own ----------------------
    active_before = sum(1 for r in working["lenders"].values() if r["status"] == "active")
    dropped_active = 0
    keys = _match_key(working)
    for notice in notices or []:
        display = keys.get(normalize_name(notice.get("lender", "")))
        if display is None:
            report.append(f"NOTICE for unknown lender {notice.get('lender')!r} — flagged, not added automatically")
            continue
        rec = working["lenders"][display]
        if rec["status"] in ("merged", "ceased"):
            continue
        if rec["status"] == "active":
            dropped_active += 1
        rec.update(status=notice["action"], successor=notice.get("successor"),
                   status_since=(notice.get("date") or today)[:4], status_source=notice.get("source", ""),
                   status_checked=today,
                   evidence=f"Regulator merger/wind-up notice ({notice.get('source', '')}, "
                            f"{notice.get('date', '')})")
        changes.append(f"TOMBSTONE {display}: -> {notice['action']}"
                       + (f" into {notice['successor']}" if notice.get("successor") else "")
                       + " (regulator notice)")

    # --- list voting ---------------------------------------------------------------------------
    for display, rec in working["lenders"].items():
        if rec["status"] in ("merged", "ceased"):
            continue
        expected = [sid for sid in rec.get("expected_in", []) if sid in source_defs]
        if not expected:
            continue
        gone = [sid for sid in expected if usable.get(sid) and normalize_name(display) not in pull_names[sid]
                and not any(normalize_name(a) in pull_names[sid] for a in rec.get("aliases", []))]
        present = [sid for sid in expected if usable.get(sid) and sid not in gone]
        if gone:
            regulator_gone = any(source_defs[sid]["regulator"] for sid in gone)
            threshold = 2 if regulator_gone else 3
            if len(gone) >= threshold:
                was = rec["status"]
                rec.update(status="ceased", successor=None, status_since=today[:4],
                           status_source=", ".join(source_defs[s]["name"] for s in gone),
                           status_checked=today,
                           evidence=f"Absent from {len(gone)} independent sources "
                                    f"({', '.join(gone)}); tombstone threshold met "
                                    f"({'regulator source among them' if regulator_gone else 'three independent sources'})")
                changes.append(f"TOMBSTONE {display}: -> ceased (absent from {', '.join(gone)})")
                if was == "active":
                    dropped_active += 1
            elif rec["status"] == "active":
                rec.update(status="unknown", status_checked=today,
                           evidence=f"Missing from {', '.join(gone)} — below the tombstone threshold "
                                    f"({'2 sources incl. the regulator' if regulator_gone else '3 sources'} "
                                    f"required); flagged for verification, kept fully present")
                changes.append(f"FLAG {display}: active -> unknown (missing from {', '.join(gone)})")
                dropped_active += 1
        elif present and rec["status"] == "unknown":
            rec.update(status="active", status_checked=today,
                       evidence=f"Listed again by {', '.join(present)}")
            changes.append(f"RESTORE {display}: unknown -> active (listed by {', '.join(present)})")

    # --- additions: names on usable lists that the registry does not know ----------------------
    known = _match_key(working)
    added = {}
    for sid, sdef in source_defs.items():
        if not usable.get(sid):
            continue
        raw_names = pulls[sid].get("names", [])
        by_norm = {normalize_name(n): n for n in raw_names if n and n.strip()}
        for norm, published in by_norm.items():
            if norm in known:
                display = known[norm]
                if sid not in working["lenders"][display].setdefault("expected_in", []):
                    working["lenders"][display]["expected_in"].append(sid)
                continue
            if norm in added:
                added[norm][1]["expected_in"].append(sid)
                continue
            added[norm] = (published, {"status": "active", "successor": None, "status_since": None,
                                       "status_source": sdef["name"], "status_checked": today,
                                       "evidence": f"First seen on the {sdef['name']} list",
                                       "kind": "credit_union" if sdef["segment"] == "credit_union" else "lender",
                                       "provinces": list(sdef["provinces"]), "expected_in": [sid],
                                       "aliases": []})
            changes.append(f"ADD {published} (from {sid})")
    for norm, (published, rec) in added.items():
        working["lenders"][published] = rec
        known[norm] = published

    # --- fail-safe 3: sanity floor --------------------------------------------------------------
    limit = max(REVIEW_DROP_ABS, math.ceil(REVIEW_DROP_PCT * active_before)) if active_before else REVIEW_DROP_ABS
    log_entry = {"date": today, "sources": {sid: {"ok": bool((pulls.get(sid) or {}).get("ok")),
                                                  "count": len(pull_names.get(sid, [])),
                                                  "usable": usable[sid]} for sid in source_defs},
                 "changes_proposed": changes, "changes_applied": False, "flags": []}
    if dropped_active > limit:
        report.append(f"REVIEW REQUIRED: this run would drop {dropped_active} active lenders "
                      f"(floor is {limit}); nothing applied")
        log_entry["flags"].append("REVIEW REQUIRED — sanity floor tripped; nothing applied")
        return None, report, log_entry

    mark_stale()
    for sid in source_defs:
        if usable[sid]:
            working["sources"][sid].update(last_good_pull=today, last_good_count=len(pull_names[sid]),
                                           stale=False, stale_since=None)
    working["updated"] = today
    working["refresh_log"].append({**log_entry, "changes_applied": True})
    report.append(f"OK: {len(changes)} change(s) applied; active lenders {active_before} -> "
                  f"{sum(1 for r in working['lenders'].values() if r['status'] == 'active')}")
    return working, report, {**log_entry, "changes_applied": True}


# --- live pulls (best effort; any failure is a stale source, never a silent change) -------------

def fetch_source(sid: str, pulls_dir: Path | None):
    """Names for one source: a saved pull file when present (the census keeps these current),
    else a light fetch of the source page. Returns (names, error)."""
    if pulls_dir:
        f = pulls_dir / f"{sid}.txt"
        if f.exists():
            return [ln.strip() for ln in f.read_text().splitlines() if ln.strip()], None
    try:
        import requests
        r = requests.get(SOURCE_DEFS[sid]["url"],
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"},
                         timeout=30)
        r.raise_for_status()
        # The list pages are JS-driven directories; a plain fetch cannot enumerate them
        # reliably, so a bare fetch is reported as an extraction failure (source goes stale)
        # rather than guessed at. Saved pull files are the supported enumeration path.
        return None, f"page fetched ({len(r.content)} bytes) but no saved pull file to enumerate from"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the updated registry (default: dry-run report only)")
    ap.add_argument("--pulls-dir", type=Path, default=None, help="directory of <source_id>.txt saved pulls")
    ap.add_argument("--notices", type=Path, default=None, help="JSON file of regulator merger/wind-up notices")
    ap.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    registry = json.loads(args.registry.read_text()) if args.registry.exists() else {
        "version": 1, "lenders": {}, "sources": {}, "refresh_log": []}
    pulls = {}
    for sid in SOURCE_DEFS:
        names, error = fetch_source(sid, args.pulls_dir)
        pulls[sid] = {"ok": names is not None, "names": names or [], "error": error}
    notices = json.loads(args.notices.read_text()) if args.notices else []
    today = date.today().isoformat()
    new_registry, report, log_entry = plan_refresh(registry, pulls, notices, today)

    text = "\n".join([f"Lender registry refresh — {today} ({'APPLY' if args.apply else 'dry run'})",
                      *report, f"log: {json.dumps(log_entry)[:400]}"])
    print(text)
    if args.report:
        args.report.write_text(text + "\n")
    if args.apply:
        if new_registry is None:
            print("REVIEW REQUIRED — registry left unchanged")
            return 2
        args.registry.write_text(json.dumps(new_registry, indent=1))
        print(f"wrote {args.registry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
