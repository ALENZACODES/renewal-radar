"""Three-level verification for every scraped lender reading.

    Level 1  Structure    the reading came from the lender's own source and is internally consistent:
                          a 5-year rate exists, every rate is 1-15%, no 3-year-plus special above its posted
                          rate, and no jump of more than 2.5 points between neighbouring terms of 1 year or more.
    Level 2  Market       the reading is plausible against independent Bank of Canada figures
                          (big-six typical 5-year posted for banks; 5-year Government of Canada bond for others).
                          This is live.validate(), unchanged.
    Level 3  Corroborated a second, independent reading of the same lender agrees within tolerance:
                          another live source from the lender in the same run, or the lender's previous
                          verified reading (0.50 points if under 3 days old, 0.75 if older, up to 14 days).

A reading is shown with the highest level it reached in order (a level-3 pass never hides a level-2 failure).
Nothing is estimated: a failed level is reported with its reason, never patched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TERM_GAP_MAX = 2.5
CORROBORATE_FRESH = 0.50
CORROBORATE_OLDER = 0.75
FRESH_DAYS = 3
MAX_AGE_DAYS = 14


def _terms(rows: list) -> dict:
    from .live import summarize
    return summarize(rows)


def level1(rows: list, lender_type: str) -> tuple[bool, str]:
    terms = _terms(rows)
    if not terms:
        return False, "no fixed-rate terms parsed"
    if 60 not in terms and not (lender_type == "alternative"):
        return False, "no 5-year fixed rate"
    for t, v in terms.items():
        for rt, r in v.items():
            if not 1.0 <= r <= 15.0:
                return False, f"{t}-month {rt} rate {r} outside 1-15%"
        if t >= 36 and "posted" in v and "special" in v and v["special"] > v["posted"] + 0.01:
            return False, f"{t}-month special {v['special']} above posted {v['posted']}"
    ordered = sorted(t for t in terms if t >= 12)        # sub-1-year terms are often open/convertible pricing
    for a, b in zip(ordered, ordered[1:]):
        for rt in set(terms[a]) & set(terms[b]):          # posted vs posted, special vs special
            ra, rb = terms[a][rt], terms[b][rt]
            if abs(ra - rb) > TERM_GAP_MAX:
                return False, f"{a}- to {b}-month {rt} jump of {abs(ra - rb):.2f} points"
    return True, f"{len(terms)} terms consistent"


def level2(rows: list, lender_type: str, anchor: dict) -> tuple[bool, str]:
    from .live import validate
    ok, why = validate(rows, lender_type, anchor)
    return ok, ("consistent with Bank of Canada reference figures" if ok else why)


def compare(rows: list, other: list) -> float | None:
    """Largest absolute difference across terms and rate types the two readings share; None if nothing shared."""
    a, b = _terms(rows), _terms(other)
    diffs = [abs(a[t][rt] - b[t][rt]) for t in a if t in b for rt in a[t] if rt in b[t]]
    return max(diffs) if diffs else None


def level3(rows: list, second: list | None = None, previous: dict | None = None,
           now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    if second:
        d = compare(rows, second)
        if d is not None:
            return (d <= CORROBORATE_FRESH,
                    f"second live source agrees within {d:.2f} points" if d <= CORROBORATE_FRESH
                    else f"second live source differs by {d:.2f} points")
    if previous and previous.get("rows"):
        try:
            at = datetime.fromisoformat(previous["at"])
        except (KeyError, TypeError, ValueError):
            at = None
        if at is not None and at < now:
            age = now - at
            if age <= timedelta(days=MAX_AGE_DAYS):
                tol = CORROBORATE_FRESH if age <= timedelta(days=FRESH_DAYS) else CORROBORATE_OLDER
                d = compare(rows, previous["rows"])
                if d is not None:
                    days = age.total_seconds() / 86400
                    return (d <= tol, f"matches the reading from {days:.1f} days ago within {d:.2f} points" if d <= tol
                            else f"moved {d:.2f} points since the reading {days:.1f} days ago; awaiting confirmation")
    return False, "no independent second reading yet"


def verify(rows: list, lender_type: str, anchor: dict, second: list | None = None,
           previous: dict | None = None, now: datetime | None = None) -> dict:
    checks, level = [], 0
    for n, name, fn in ((1, "structure", lambda: level1(rows, lender_type)),
                        (2, "market", lambda: level2(rows, lender_type, anchor)),
                        (3, "corroborated", lambda: level3(rows, second, previous, now))):
        ok, detail = fn()
        checks.append({"level": n, "name": name, "ok": ok, "detail": detail})
        if ok and level == n - 1:
            level = n
    return {"level": level, "of": 3, "checks": checks}
