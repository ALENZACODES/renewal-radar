"""Page fetchers. Static HTTP by default; a headless browser only when installed."""
from __future__ import annotations

import os
from typing import Protocol

DEFAULT_CONTACT = 'https://github.com/ALENZACODES'


def user_agent() -> str:
    contact = os.environ.get('RR_SCRAPER_CONTACT', DEFAULT_CONTACT)
    return f'RenewalRadarBot/1.0 (+{contact}; posted-rate research, one request per lender per day)'


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


class HttpFetcher:
    """Plain GET with an identifying user agent, size cap and no cookies."""

    def __init__(self, timeout: float = 30.0, max_bytes: int = 5_000_000) -> None:
        import httpx
        self._client = httpx.Client(timeout=timeout, follow_redirects=True,
                                    headers={'User-Agent': user_agent(), 'Accept': 'text/html'})
        self._max = max_bytes

    def get(self, url: str) -> str:
        with self._client.stream('GET', url) as resp:
            resp.raise_for_status()
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > self._max:
                    raise ValueError(f'response from {url} exceeds {self._max} bytes')
            return body.decode(resp.encoding or 'utf-8', errors='replace')

    def close(self) -> None:
        self._client.close()


class BrowserFetcher:
    """Headless Chromium for pages that render rates with JavaScript (needs playwright)."""

    def __init__(self, settle_ms: int = 6000, timeout_ms: int = 60_000) -> None:
        self.settle_ms = settle_ms
        self.timeout_ms = timeout_ms

    def get(self, url: str) -> str:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=user_agent())
                page.goto(url, wait_until='domcontentloaded', timeout=self.timeout_ms)
                page.wait_for_timeout(self.settle_ms)
                return page.content()
            finally:
                browser.close()
