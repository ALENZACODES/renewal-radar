"""Automatic official-source rate tracking; cached values never become live quotes."""
from __future__ import annotations

import asyncio
import copy
import math
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable

from .market import fetch_boc, SERIES
from ..providers.bank_rates import fetch_bank_posted_rates


class LiveRateTracker:
    def __init__(self, *, boc_provider=fetch_boc, bank_provider=fetch_bank_posted_rates,
                 interval_seconds: int = 900, minimum_refresh_seconds: int = 30,
                 monotonic: Callable = time.monotonic,
                 clock: Callable = lambda: datetime.now(timezone.utc)):
        if not 30 <= interval_seconds <= 86400:
            raise ValueError("Rate refresh interval must be 30 seconds through one day")
        if not 1 <= minimum_refresh_seconds <= interval_seconds:
            raise ValueError("Invalid rate refresh throttle")
        self.boc_provider = boc_provider
        self.bank_provider = bank_provider
        self.interval_seconds = interval_seconds
        self.minimum_refresh_seconds = minimum_refresh_seconds
        self.monotonic = monotonic
        self.clock = clock
        self._lock = asyncio.Lock()
        self._task = None
        self._last_refresh = None
        self._snapshot = None
        self._changes = []
        self._latest_values = {}
        self._revision = 0

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.refresh()

    @staticmethod
    def _finite_rate(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and -10 <= value <= 50

    def _clean_market(self, payload, checked_at):
        if not isinstance(payload, dict):
            return {"data_status": "unavailable", "series": {}, "checked_at": checked_at}
        market = copy.deepcopy(payload)
        market["series"] = {}
        supplied = payload.get("series", {})
        if isinstance(supplied, dict):
            for key, observation in supplied.items():
                if key not in SERIES or not isinstance(observation, dict):
                    continue
                if not self._finite_rate(observation.get("value")):
                    continue
                try:
                    observed = date.fromisoformat(str(observation.get("observed_at")))
                except ValueError:
                    continue
                if observed > self.clock().date():
                    continue
                if not str(observation.get("source_url", "")).startswith("https://www.bankofcanada.ca/valet/"):
                    continue
                market["series"][key] = observation
        if not market["series"]:
            market["data_status"] = "unavailable"
        elif market.get("from_cache") or market.get("data_status") != "live-observation":
            market["data_status"] = "cached-stale"
        else:
            market["data_status"] = "live-observation"
        market["checked_at"] = checked_at
        return market

    def _clean_banks(self, payload):
        banks = []
        if not isinstance(payload, list):
            return banks
        for item in payload[:12]:
            if not isinstance(item, dict):
                continue
            bank = copy.deepcopy(item)
            if bank.get("verified") is not True or not self._finite_rate(bank.get("quote")) or bank["quote"] <= 0:
                bank.update(verified=False, quote=None, status="needs-verification")
            banks.append(bank)
        return banks

    def _record_changes(self, market, checked_at):
        if market.get("data_status") != "live-observation":
            return
        for key, item in market["series"].items():
            current = item["value"]
            previous = self._latest_values.get(key)
            if previous is not None and previous != current:
                change = Decimal(str(current)) - Decimal(str(previous))
                self._changes.append({
                    "series": key, "label": item.get("label", key),
                    "previous": previous, "current": current,
                    "change_basis_points": float(change * 100),
                    "observed_at": item["observed_at"], "checked_at": checked_at,
                    "source_url": item["source_url"],
                })
            self._latest_values[key] = current
        self._changes = self._changes[-200:]

    async def refresh(self):
        async with self._lock:
            now = self.monotonic()
            if self._snapshot is not None and self._last_refresh is not None and now - self._last_refresh < self.minimum_refresh_seconds:
                return self.snapshot(throttled=True)
            checked_at = self.clock().isoformat()
            results = await asyncio.gather(self.boc_provider(force=True), self.bank_provider(), return_exceptions=True)
            boc_result, bank_result = results
            warnings = []
            if isinstance(boc_result, Exception):
                boc_result = {"data_status": "unavailable", "series": {}}
                if self._snapshot:
                    boc_result = {**self._snapshot["market"], "data_status": "cached-stale", "from_cache": True}
                warnings.append("Bank of Canada retrieval failed; no new observation was invented.")
            if isinstance(bank_result, Exception):
                bank_result = []
                warnings.append("Official lender pages could not be checked.")
            market = self._clean_market(boc_result, checked_at)
            banks = self._clean_banks(bank_result)
            self._record_changes(market, checked_at)
            self._revision += 1
            self._last_refresh = self.monotonic()
            self._snapshot = {
                "provider": "official-rate-tracker-v17", "revision": self._revision,
                "checked_at": checked_at, "refresh_interval_seconds": self.interval_seconds,
                "data_status": market["data_status"], "market": market, "banks": banks,
                "changes": list(reversed(self._changes)), "warnings": warnings,
                "verified_bank_count": sum(bank.get("verified") is True for bank in banks),
                "personalized_quotes_included": False,
            }
            return self.snapshot()

    def snapshot(self, *, throttled=False):
        result = copy.deepcopy(self._snapshot or {
            "provider": "official-rate-tracker-v17", "revision": 0,
            "checked_at": None, "refresh_interval_seconds": self.interval_seconds,
            "data_status": "not-checked", "market": {"series": {}, "data_status": "not-checked"},
            "banks": [], "changes": [], "warnings": [], "verified_bank_count": 0,
            "personalized_quotes_included": False,
        })
        result["throttled"] = throttled
        result["automatic_refresh_running"] = self._task is not None and not self._task.done()
        return result
