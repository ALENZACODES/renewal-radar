"""Daily recorder: every lender's own posted rates, every day, from now on.

    python -m renewal.ratewatch.recorder            # one recording pass; safe to run any number of times a day

Five layers so a day is never lost to one failure:
  1. Retry with backoff  - lenders not recorded on the first pass are retried (30 s, 2 min, 5 min).
  2. Second source       - each lender's backup feed or rediscovered page (collect()).
  3. Self-repair         - the lender's own site is searched again for its rates page (read_rediscovered).
  4. Redundant schedule  - run 3x a day + at logon, catch up after missed runs; already-recorded lenders are skipped.
  5. Watchdog + defaults - nothing is ever invented: an unrecorded day stays covered by the labelled gap fill and the
                           board shows the last good reading; 3 failed days in a row raise an alert in ALERTS.txt.
Only validated bank-own readings are written to history (how = api | html), exactly as the live board does.
"""
import json, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from . import history, live
from .paths import DATA

HEALTH = DATA / "recorder_health.json"
ALERTS = DATA / "ALERTS.txt"
LOG_DIR = DATA / "recorder_logs"
BACKOFF = (30, 120, 300)
ALERT_AFTER_DAYS = 3


def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG_DIR / f"{date.today():%Y-%m}.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ever_recorded(lid) -> bool:
    """Has this lender ever published a reading we could record? Lenders that never have (most private lenders)
    get one attempt per run instead of the full backoff rounds."""
    with history.db() as c:
        return c.execute("SELECT 1 FROM rates WHERE source=? AND how IN ('api','html') LIMIT 1", (lid,)).fetchone() is not None


def recorded_today(lid, day=None) -> bool:
    day = (day or date.today()).isoformat()
    with history.db() as c:
        return c.execute("SELECT 1 FROM rates WHERE source=? AND day=? AND how IN ('api','html') LIMIT 1",
                         (lid, day)).fetchone() is not None


def refresh_boc():
    """Bank of Canada series for validation and gap fills; stored figures are the default if it is unreachable."""
    for wait in (0,) + BACKOFF[:2]:
        time.sleep(wait)
        try:
            history.official(start=(date.today() - timedelta(days=60)).isoformat())
            return True
        except Exception as e:                       # noqa: BLE001 - any failure falls back to stored figures
            log(f"Bank of Canada refresh failed ({type(e).__name__}); retrying")
    log("Bank of Canada unreachable; using stored figures")
    return False


# Hosts that did not answer during this run. A lender's edge network that is blocking us is never hammered:
# once a host fails it is left alone for the rest of the run, so a temporary block can expire.
UNREACHABLE: set = set()


def host(url):
    from urllib.parse import urlparse
    h = urlparse(url).hostname or ""
    return h[4:] if h.startswith("www.") else h


def _urls(lender):
    return [lender[3][1]] + ([lender[4][1]] if lender[4] else [])


def collect(lender, anchor, now):
    """Layer 2: the lender's live sources only (primary, then its backup feed or rediscovered page), validated.
    Archive copies are never a reading for today, so the slow archive tier of the board chain is not used here."""
    lid, name, ltype, (pkind, purl), backup = lender
    tries = [("primary", lambda: live.read_live(pkind, purl), purl)]
    if backup:
        tries.append(("backup1", lambda: live.read_live(backup[0], backup[1]), backup[1]))
    else:
        tries.append(("backup1", lambda: live.read_rediscovered(purl)[0], purl))
    reasons = []
    for tier, fn, url in tries:
        if host(url) in UNREACHABLE:
            reasons.append(f"{tier} skipped: {host(url)} not answering this run")
            continue
        try:
            rows = fn()
        except Exception as e:                       # noqa: BLE001
            import requests
            if isinstance(e, (requests.ConnectionError, requests.Timeout)):
                UNREACHABLE.add(host(url))
            reasons.append(f"{tier} {type(e).__name__}")
            continue
        if not rows:
            reasons.append(f"{tier} no rates")
            continue
        ok, why = live.validate(rows, ltype, anchor)
        if not ok:
            reasons.append(f"{tier} rejected: {why}")
            continue
        history.save(lid, now.astimezone().date().isoformat(), rows, "api" if pkind.endswith("_api") and tier == "primary" else "html")
        live._save_cache(lid, {"at": now.isoformat(timespec="seconds"), "tier": tier, "url": url, "rows": rows})
        return True, tier
    return False, "; ".join(reasons)


ARCHIVE_FRESH_DAYS = 3


def archive_copy(lender, anchor, today=None):
    """Layer 6: when the lender's own site cannot be reached, look (without contacting the lender) for a copy of the
    lender's own page or feed that a public archive captured in the last ARCHIVE_FRESH_DAYS days. It is the lender's
    own published rates, saved under the archive's capture date and labelled how='wayback'."""
    import requests
    lid, name, ltype, (pkind, purl), backup = lender
    today = today or date.today()
    start = (today - timedelta(days=ARCHIVE_FRESH_DAYS)).strftime("%Y%m%d")
    for kind, url in [(pkind, purl)] + ([backup] if backup else []):
        if kind == "td_api":
            continue                                  # a POST: archives never hold it
        try:
            r = requests.get("https://web.archive.org/cdx/search/cdx", timeout=60, headers={"User-Agent": "Mozilla/5.0"},
                             params={"url": url.split("://", 1)[1].split("?")[0], "matchType": "prefix", "from": start,
                                     "filter": "statuscode:200", "fl": "timestamp,original"})
            caps = [line.split(" ", 1) for line in r.text.splitlines() if " " in line]
        except Exception:                             # noqa: BLE001
            continue
        for ts, orig in sorted(caps, reverse=True)[:2]:
            try:
                from . import backfill
                body = backfill.body_text(requests.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=90,
                                                       headers={"User-Agent": "Mozilla/5.0"}))
            except Exception:                         # noqa: BLE001
                continue
            rows = live.parse_text(kind, body)
            day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            ok, why = live.validate(rows, ltype, anchor) if rows else (False, "no rates")
            if ok and not recorded_today(lid, date.fromisoformat(day)):
                history.save(lid, day, rows, "wayback")
                return True, f"archive copy of {name}'s own rates captured {day}"
    return False, "no fresh archive copy"


def self_repair(lender, anchor, now):
    """Layer 3: search the lender's own site for its rates page again and validate what it finds."""
    lid, name, ltype, (pkind, purl), backup = lender
    if host(purl) in UNREACHABLE:
        return False, f"self-repair skipped: {host(purl)} not answering this run"
    try:
        rows, note = live.read_rediscovered(purl)
    except Exception as e:                           # noqa: BLE001
        return False, f"self-repair error {type(e).__name__}"
    if not rows:
        return False, "self-repair found no rates"
    ok, why = live.validate(rows, ltype, anchor)
    if not ok:
        return False, f"self-repair rejected: {why}"
    history.save(lid, now.astimezone().date().isoformat(), rows, "html")
    live._save_cache(lid, {"at": now.isoformat(timespec="seconds"), "tier": "backup1", "url": purl, "rows": rows})
    return True, "self-repair: " + (note or "rediscovered rates page")


def fail_streak(lid, since, day=None):
    """Consecutive days up to `day` with no own reading, counting only days since the recorder started."""
    day = day or date.today()
    n, d = 0, day
    while d >= since and not recorded_today(lid, d):
        n, d = n + 1, d - timedelta(days=1)
    return n


def watchdog(missing, day=None):
    """Layer 5: alert when a lender has had no own reading for ALERT_AFTER_DAYS days in a row."""
    day = day or date.today()
    h = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
    since = date.fromisoformat(h.setdefault("started", day.isoformat()))
    names = {l[0]: l[1] for l in live.LENDERS}
    alerts, status = [], {}
    for lid, name in names.items():
        streak = fail_streak(lid, since, day) if lid in missing else 0
        status[lid] = {"name": name, "fail_days": streak, "checked": day.isoformat()}
        if streak >= ALERT_AFTER_DAYS:
            alerts.append(f"{day} {name} ({lid}): no own reading for {streak} days in a row. Its page or feed has "
                          f"probably changed: see the FIX notes in ratewatch/scrape.py and docs/RATEWATCH.md.")
    h["lenders"] = status
    HEALTH.write_text(json.dumps(h, indent=1))
    if alerts:
        with open(ALERTS, "a", encoding="utf-8") as fh:
            fh.write("\n".join(alerts) + "\n")
        for x in alerts:
            log("ALERT " + x)
    return alerts


@contextmanager
def collecting(sleep=time.sleep, max_wait=600):
    """Hold the live board's OS lock only while fetching (never during retry waits), so the board stays usable.
    If the board is mid-refresh, wait for it (up to max_wait), then collect anyway: reads are idempotent."""
    fh = open(live.REFRESH_LOCK, "a+b")
    held, waited = False, 0
    try:
        while not (held := live._try_os_lock(fh)) and waited < max_wait:
            sleep(5)
            waited += 5
        yield held
    finally:
        if held:
            live._os_unlock(fh)
        fh.close()


def _safe_collect(l, anchor, now):
    try:
        return collect(l, anchor, now)
    except Exception as e:                           # noqa: BLE001 - one lender never stops the pass
        return False, f"error {type(e).__name__}"


def run(lenders=None, sleep=time.sleep):
    lenders = lenders or live.LENDERS
    log(f"recording pass start: {len(lenders)} lenders")
    refresh_boc()
    UNREACHABLE.clear()                                        # each run gives every site a fresh chance
    todo = [l for l in lenders if not recorded_today(l[0])]
    log(f"{len(lenders) - len(todo)} already recorded today; {len(todo)} to collect")
    skipped = []
    if todo:
        anchor = live.market_anchor()
        for attempt, wait in enumerate((0,) + BACKOFF):        # layers 1 + 2: live sources, retried with backoff
            if not todo:
                break
            if wait:
                live.TIMEOUT = min(20 * (attempt + 1), 60)      # slow sites get longer on each retry
                log(f"retry {attempt}: {len(todo)} lenders after {wait}s (timeout {live.TIMEOUT}s)")
                sleep(wait)
            now = datetime.now(timezone.utc)
            with collecting(sleep):
                with ThreadPoolExecutor(8) as ex:
                    results = list(ex.map(lambda l: (l, _safe_collect(l, anchor, now)), todo))
            for l, (ok, why) in results:
                if not ok and wait == BACKOFF[-1]:
                    log(f"{l[1]}: {why}")
            todo = [l for l in todo if not recorded_today(l[0])]
            blocked = [l for l in todo if all(host(u) in UNREACHABLE for u in _urls(l))]
            if blocked:                                         # their sites are not answering: do not hammer them
                for l in blocked:
                    log(f"{l[1]}: {', '.join(sorted({host(u) for u in _urls(l)}))} not answering; left alone this run")
                todo = [l for l in todo if l not in blocked]
                skipped += blocked
            if attempt == 0:                                    # never-published lenders: one try per run is enough
                never = [l for l in todo if not ever_recorded(l[0])]
                todo = [l for l in todo if l not in never]
                skipped += never
                if never:
                    log(f"{len(never)} lenders have never published rates; tried once this run")

        live.TIMEOUT = 20
        now = datetime.now(timezone.utc)
        with collecting(sleep):
            for l in list(todo) + skipped:                     # layer 3
                ok, why = self_repair(l, anchor, now)
                log(f"{l[1]}: {why}")
                if ok and l in todo:
                    todo.remove(l)
        for l in [x for x in todo + skipped if not recorded_today(x[0]) and ever_recorded(x[0])]:   # layer 6
            ok, why = archive_copy(l, anchor)
            if ok:
                log(f"{l[1]}: {why}")
    todo += [l for l in skipped if not recorded_today(l[0])]
    missing = {l[0] for l in todo}
    for l in todo:
        log(f"{l[1]}: not recorded today; the board keeps its last good reading and the month stays covered by "
            f"the labelled gap fill")
    alerts = watchdog(missing)
    try:                                                       # keep monthly coverage and the audit current
        from . import backfill
        backfill.fill_gaps()
    except Exception as e:                                     # noqa: BLE001
        log(f"gap-fill refresh skipped ({type(e).__name__})")
    log(f"recording pass done: {len(lenders) - len(missing)}/{len(lenders)} recorded today, {len(alerts)} alerts")
    return {"recorded": len(lenders) - len(missing), "missing": sorted(missing), "alerts": alerts}


if __name__ == "__main__":
    try:
        run()
    except Exception:                                          # last resort: log, exit non-zero so the task retries
        log("recorder crashed:\n" + traceback.format_exc())
        sys.exit(1)
