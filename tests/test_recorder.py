"""Daily recorder: retries, self-repair, skip-already-recorded, watchdog alerts. No network."""
from datetime import date, timedelta
import pytest
from renewal.ratewatch import history, live, recorder

L1 = ("P021", "RBC", "bank", ("html", "https://example.test/rbc"), None)
L2 = ("P023", "TD", "bank", ("td_api", "https://example.test/td"), None)
ROWS = [(60, "fixed_closed", "posted", 6.09), (36, "fixed_closed", "posted", 6.05)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB", tmp_path / "rates.db", raising=False)
    for name in ("HEALTH", "ALERTS"):
        monkeypatch.setattr(recorder, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(recorder, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(live, "BOARD", tmp_path / "board.json")
    monkeypatch.setattr(live, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(live, "REFRESH_LOCK", tmp_path / "refresh.lock")
    monkeypatch.setattr(live, "LENDERS", [L1, L2])
    monkeypatch.setattr(recorder, "refresh_boc", lambda: True)
    monkeypatch.setattr(live, "market_anchor", lambda: {"goc_5y": 3.0, "boc_5y_posted": 6.09})
    import renewal.ratewatch.backfill as bf
    monkeypatch.setattr(bf, "fill_gaps", lambda *a, **k: {})
    for lid in ("P021", "P023"):                             # both banks have published before (not never-published)
        history.save(lid, "2026-01-05", ROWS, "html")
    return tmp_path


def _collector(fail_times):
    calls = {}

    def collect(lender, anchor, now):
        calls[lender[0]] = calls.get(lender[0], 0) + 1
        if calls[lender[0]] > fail_times.get(lender[0], 0):
            history.save(lender[0], now.astimezone().date().isoformat(), ROWS, "html")
            return True, "primary"
        return False, "primary ConnectionError"
    return collect, calls


def test_retries_until_recorded_and_skips_already_recorded(env, monkeypatch):
    collect, calls = _collector({"P023": 2})                 # TD fails twice, then works
    monkeypatch.setattr(recorder, "collect", collect)
    waits = []
    out = recorder.run(sleep=waits.append)
    assert out["recorded"] == 2 and out["missing"] == []
    assert calls == {"P021": 1, "P023": 3} and waits == [30, 120]
    out = recorder.run(sleep=waits.append)                  # second run the same day: nothing re-collected
    assert calls == {"P021": 1, "P023": 3}


def test_self_repair_when_every_retry_fails(env, monkeypatch):
    collect, _ = _collector({"P023": 99})
    monkeypatch.setattr(recorder, "collect", collect)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: (ROWS, "https://example.test/td/new-rates"))
    monkeypatch.setattr(live, "validate", lambda rows, t, a: (True, "ok"))
    out = recorder.run(sleep=lambda s: None)
    assert out["missing"] == [] and recorder.recorded_today("P023")


def test_nothing_invented_and_alert_after_three_days(env, monkeypatch):
    collect, _ = _collector({"P023": 99})
    monkeypatch.setattr(recorder, "collect", collect)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: ([], None))
    out = recorder.run(sleep=lambda s: None)
    assert out["missing"] == ["P023"] and not recorder.recorded_today("P023")   # no fabricated row
    today = date.today()
    import json
    h = json.loads(recorder.HEALTH.read_text())
    h["started"] = (today - timedelta(days=5)).isoformat()
    recorder.HEALTH.write_text(json.dumps(h))
    alerts = recorder.watchdog({"P023"}, today)
    assert alerts and "TD (P023)" in alerts[0] and "6 days" in alerts[0]
    assert recorder.watchdog(set(), today) == []


def test_collect_uses_backup_when_primary_fails(env, monkeypatch):
    from datetime import datetime, timezone
    lender = ("ALT02", "EQ", "alternative", ("html", "https://example.test/a"), ("equitable", "https://example.test/b"))
    def read_live(kind, url):
        if kind == "html":
            raise ConnectionError("down")
        return ROWS
    monkeypatch.setattr(live, "read_live", read_live)
    monkeypatch.setattr(live, "validate", lambda rows, t, a: (True, "ok"))
    ok, tier = recorder.collect(lender, {}, datetime.now(timezone.utc))
    assert ok and tier == "backup1" and recorder.recorded_today("ALT02")


def test_board_lock_is_free_during_retry_waits(env, monkeypatch):
    collect, _ = _collector({"P023": 2})
    monkeypatch.setattr(recorder, "collect", collect)
    free = []

    def sleep(s):                                            # another process trying to refresh the board meanwhile
        fh = open(live.REFRESH_LOCK, "a+b")
        try:
            got = live._try_os_lock(fh)
            free.append(got)
            if got:
                live._os_unlock(fh)
        finally:
            fh.close()
    recorder.run(sleep=sleep)
    assert free == [True, True]


def test_never_published_lender_gets_one_try_not_backoff_rounds(env, monkeypatch):
    alt = ("ALT20", "Private MIC", "alternative", ("html", "https://example.test/mic"), None)
    monkeypatch.setattr(live, "LENDERS", [L1, alt])
    collect, calls = _collector({"ALT20": 99})
    monkeypatch.setattr(recorder, "collect", collect)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: ([], None))
    waits = []
    out = recorder.run(sleep=waits.append)
    assert calls["ALT20"] == 1 and waits == [] and out["missing"] == ["ALT20"]


def test_never_published_lender_that_self_repairs_is_recorded(env, monkeypatch):
    alt = ("ALT20", "Private MIC", "alternative", ("html", "https://example.test/mic"), None)
    monkeypatch.setattr(live, "LENDERS", [alt])
    collect, _ = _collector({"ALT20": 99})
    monkeypatch.setattr(recorder, "collect", collect)
    monkeypatch.setattr(live, "read_rediscovered", lambda url: (ROWS, "https://example.test/mic/rates"))
    monkeypatch.setattr(live, "validate", lambda rows, t, a: (True, "ok"))
    out = recorder.run(sleep=lambda s: None)
    assert out["missing"] == [] and recorder.recorded_today("ALT20")


def test_http_falls_back_to_system_curl_when_python_client_is_dropped(monkeypatch):
    import requests
    def dropped(*a, **k):
        raise requests.ConnectionError("edge dropped python client")
    monkeypatch.setattr(requests, "get", dropped)
    monkeypatch.setattr(live, "_curl", lambda url, headers: live._CurlResponse(url, 200, b'{"ok": 1}'))
    r = live._http("https://lender.test/rates.json")
    assert r.ok and r.json() == {"ok": 1}


def test_readings_are_dated_by_the_local_calendar_day(env, monkeypatch):
    from datetime import datetime, timezone
    late = datetime(2026, 10, 17, 3, 30, tzinfo=timezone.utc)      # 23:30 the previous evening in Toronto
    lender = ("CU99", "Test CU", "credit_union", ("html", "https://example.test/cu"), None)
    monkeypatch.setattr(live, "read_live", lambda kind, url: ROWS)
    monkeypatch.setattr(live, "validate", lambda rows, t, a: (True, "ok"))
    recorder.collect(lender, {}, late)
    with history.db() as c:
        days = [d for (d,) in c.execute("SELECT DISTINCT day FROM rates WHERE source='CU99'")]
    assert days == [late.astimezone().date().isoformat()]
