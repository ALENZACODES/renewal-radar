import asyncio
from datetime import datetime, timezone

import pytest

from renewal.services.market_tracker_v17 import LiveRateTracker


def observation(value=4.75, status="live-observation"):
    return {"data_status": status, "from_cache": status != "live-observation", "series": {
        "prime": {"value": value, "label": "Typical bank prime", "observed_at": "2026-10-13",
                  "source_url": "https://www.bankofcanada.ca/valet/observations/V80691311/json"},
    }}


def tracker(payload=None, banks=None):
    async def boc_provider(force=False):
        assert force is True
        return observation() if payload is None else payload

    async def bank_provider():
        return [] if banks is None else banks

    return LiveRateTracker(boc_provider=boc_provider, bank_provider=bank_provider,
                           clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))


def test_tracker_reports_live_retrieval_and_throttles_repeated_requests():
    async def run():
        service = tracker()
        first = await service.refresh()
        second = await service.refresh()
        assert first["data_status"] == "live-observation"
        assert first["market"]["series"]["prime"]["value"] == 4.75
        assert second["revision"] == 1
        assert second["throttled"] is True
    asyncio.run(run())


def test_rate_changes_are_recorded_in_basis_points():
    async def run():
        value = [4.75]
        tick = [0]
        async def boc_provider(force=False):
            return observation(value[0])
        async def banks():
            return []
        service = LiveRateTracker(boc_provider=boc_provider, bank_provider=banks,
                                  monotonic=lambda: tick[0],
                                  clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))
        await service.refresh()
        value[0] = 4.5
        tick[0] = 31
        snapshot = await service.refresh()
        assert snapshot["changes"][0]["change_basis_points"] == -25
        assert snapshot["changes"][0]["previous"] == 4.75
        assert snapshot["changes"][0]["current"] == 4.5
    asyncio.run(run())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "4.75", True, 100])
def test_invalid_official_observations_cannot_be_promoted(value):
    snapshot = asyncio.run(tracker(observation(value)).refresh())
    assert snapshot["data_status"] == "unavailable"
    assert snapshot["market"]["series"] == {}


def test_cached_payload_stays_cached_and_does_not_record_live_changes():
    snapshot = asyncio.run(tracker(observation(status="cached-stale")).refresh())
    assert snapshot["data_status"] == "cached-stale"
    assert snapshot["changes"] == []


def test_unverified_lender_numbers_are_removed_from_active_quotes():
    snapshot = asyncio.run(tracker(banks=[{"lender": "Bank", "quote": 4.5, "verified": False}]).refresh())
    assert snapshot["banks"][0]["quote"] is None
    assert snapshot["verified_bank_count"] == 0


def test_verified_lender_numbers_are_retained_with_their_source_state():
    snapshot = asyncio.run(tracker(banks=[{"lender": "Bank", "quote": 4.5, "verified": True, "source_url": "https://official.example/"}]).refresh())
    assert snapshot["banks"][0]["quote"] == 4.5
    assert snapshot["verified_bank_count"] == 1


def test_provider_failure_never_substitutes_a_rate():
    async def fail(force=False):
        raise RuntimeError("Provider failed")
    service = tracker()
    service.boc_provider = fail
    snapshot = asyncio.run(service.refresh())
    assert snapshot["data_status"] == "unavailable"
    assert snapshot["market"]["series"] == {}
    assert snapshot["warnings"]


def test_snapshot_is_detached_from_internal_rate_state():
    service = tracker()
    first = asyncio.run(service.refresh())
    first["market"]["series"]["prime"]["value"] = 99
    assert service.snapshot()["market"]["series"]["prime"]["value"] == 4.75


def test_background_tracker_starts_once_and_stops_cleanly():
    async def run():
        service = tracker()
        service.start()
        original = service._task
        service.start()
        assert service._task is original
        assert service.snapshot()["automatic_refresh_running"] is True
        await service.stop()
        assert service.snapshot()["automatic_refresh_running"] is False
    asyncio.run(run())


def test_invalid_tracker_intervals_are_rejected():
    with pytest.raises(ValueError):
        LiveRateTracker(interval_seconds=1)
    with pytest.raises(ValueError):
        LiveRateTracker(minimum_refresh_seconds=1000)
