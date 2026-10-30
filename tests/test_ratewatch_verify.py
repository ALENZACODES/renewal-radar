"""Three-level verification of scraped lender readings and the scheduled-board merge."""
from datetime import datetime, timedelta, timezone

from renewal.ratewatch import live, verify

ANCHOR = {"boc_5y_posted": 6.09, "goc_5y": 3.0}
ROWS = [(12, "fixed_closed", "posted", 6.09), (36, "fixed_closed", "posted", 6.05),
        (60, "fixed_closed", "posted", 6.09), (60, "fixed_closed", "special", 4.29)]
NOW = datetime(2026, 10, 29, 20, tzinfo=timezone.utc)


def test_levels_one_and_two_without_a_second_reading():
    v = verify.verify(ROWS, "bank", ANCHOR, now=NOW)
    assert v["level"] == 2 and [c["ok"] for c in v["checks"]] == [True, True, False]


def test_level_three_from_previous_reading_and_second_source():
    prev = {"at": (NOW - timedelta(days=1)).isoformat(), "rows": ROWS}
    assert verify.verify(ROWS, "bank", ANCHOR, previous=prev, now=NOW)["level"] == 3
    assert verify.verify(ROWS, "bank", ANCHOR, second=ROWS, now=NOW)["level"] == 3


def test_big_move_is_not_corroborated():
    prev = {"at": (NOW - timedelta(days=1)).isoformat(), "rows": ROWS}
    moved = [(t, k, rt, r + 0.8) for t, k, rt, r in ROWS]
    v = verify.verify(moved, "bank", {"boc_5y_posted": 6.89, "goc_5y": 3.0}, previous=prev, now=NOW)
    assert v["level"] == 2 and "awaiting confirmation" in v["checks"][2]["detail"]


def test_old_previous_reading_does_not_corroborate():
    prev = {"at": (NOW - timedelta(days=20)).isoformat(), "rows": ROWS}
    assert verify.verify(ROWS, "bank", ANCHOR, previous=prev, now=NOW)["level"] == 2


def test_levels_are_sequential():
    bad = ROWS + [(24, "fixed_closed", "posted", 9.9)]
    v = verify.verify(bad, "bank", ANCHOR, second=bad, now=NOW)
    assert v["level"] == 0 and not v["checks"][0]["ok"]


def test_merge_fills_only_lenders_the_server_could_not_read():
    snap = {"refreshed_at": NOW.isoformat(), "anchor": ANCHOR,
            "banks": [{"id": "P021", "name": "RBC", "tier": "primary", "as_of": NOW.isoformat(), "verification": {"level": 3}},
                      {"id": "P023", "name": "TD", "tier": "primary", "as_of": NOW.isoformat(), "verification": {"level": 3}},
                      {"id": "P025", "name": "Scotiabank", "tier": "primary", "as_of": NOW.isoformat(), "verification": {"level": 1}}],
            "credit_unions": []}
    mine = {"refreshed_at": NOW.isoformat(), "banks": [
        {"id": "P021", "name": "RBC", "tier": "boc_typical"},
        {"id": "P023", "name": "TD", "tier": "primary", "own": True},
        {"id": "P025", "name": "Scotiabank", "tier": "unavailable"}], "credit_unions": []}
    out = live.merge_published(mine, snap, now=NOW)
    by = {r["id"]: r for r in out["banks"]}
    assert by["P021"]["tier"] == "published"          # filled from the scheduled verified scrape
    assert by["P023"].get("own")                      # the server's own reading is never replaced
    assert by["P025"]["tier"] == "unavailable"        # below level 2 is never published
    assert out["published"]["lenders_filled"] == 1


def test_merge_skips_stale_snapshot_rows():
    old = (NOW - timedelta(days=30)).isoformat()
    snap = {"refreshed_at": old, "banks": [{"id": "P021", "tier": "primary", "as_of": old, "verification": {"level": 3}}]}
    out = live.merge_published({"refreshed_at": NOW.isoformat(), "banks": []}, snap, now=NOW)
    assert out["banks"] == []


def test_short_terms_are_not_held_to_the_long_term_rules():
    rows = ROWS + [(6, "fixed_closed", "posted", 9.5), (12, "fixed_closed", "special", 6.12)]
    assert verify.level1(rows, "bank")[0]
